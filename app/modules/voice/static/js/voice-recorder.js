/**
 * Voice dictation recorder.
 * Attaches to #voice-mic-btn, records audio via MediaRecorder,
 * sends to /voice/transcribe, inserts result into Tiptap editor.
 */
(function () {
  var micBtn = document.getElementById('voice-mic-btn');
  if (!micBtn) return;

  var mediaRecorder = null;
  var audioChunks = [];
  var isRecording = false;

  micBtn.addEventListener('click', function () {
    if (isRecording) {
      stopRecording();
    } else {
      startRecording();
    }
  });

  function startRecording() {
    navigator.mediaDevices.getUserMedia({ audio: true })
      .then(function (stream) {
        // Pick a supported MIME type
        var mimeType = 'audio/webm;codecs=opus';
        if (!MediaRecorder.isTypeSupported(mimeType)) {
          mimeType = 'audio/webm';
        }
        if (!MediaRecorder.isTypeSupported(mimeType)) {
          mimeType = '';  // let browser pick default
        }

        var options = mimeType ? { mimeType: mimeType } : {};
        mediaRecorder = new MediaRecorder(stream, options);
        audioChunks = [];

        mediaRecorder.ondataavailable = function (e) {
          if (e.data.size > 0) audioChunks.push(e.data);
        };

        mediaRecorder.onstop = function () {
          stream.getTracks().forEach(function (t) { t.stop(); });
          sendAudio();
        };

        mediaRecorder.start();
        isRecording = true;
        micBtn.classList.add('recording');
        micBtn.title = 'Stop recording';
      })
      .catch(function (err) {
        console.error('Microphone access denied:', err);
        alert('Microphone access is required for voice dictation.');
      });
  }

  function stopRecording() {
    if (mediaRecorder && mediaRecorder.state !== 'inactive') {
      mediaRecorder.stop();
    }
    isRecording = false;
    micBtn.classList.remove('recording');
    micBtn.classList.add('processing');
    micBtn.title = 'Processing...';
  }

  function sendAudio() {
    var blob = new Blob(audioChunks, { type: mediaRecorder.mimeType || 'audio/webm' });
    var formData = new FormData();
    formData.append('audio', blob, 'recording.webm');

    fetch('/voice/transcribe', { method: 'POST', body: formData })
      .then(function (resp) { return resp.json(); })
      .then(function (data) {
        if (data.text && data.text.trim()) {
          var editor = window.tiptapEditor;
          if (editor && editor.commands) {
            try {
              editor.chain().focus().insertContent(data.text + ' ').run();
              return;
            } catch (e) {
              console.warn('Tiptap insert failed, falling back to textarea.', e);
            }
          }

          var textarea = document.getElementById('note-textarea');
          if (textarea) {
            var prefix = textarea.value ? ' ' : '';
            textarea.value = textarea.value + prefix + data.text + ' ';
            textarea.dispatchEvent(new Event('input', { bubbles: true }));
          }
        } else if (data.error) {
          console.error('Transcription error:', data.error);
          alert('Transcription error: ' + data.error);
        } else {
          alert('Не удалось распознать речь. Попробуйте говорить чуть громче и без пауз.');
        }
      })
      .catch(function (err) {
        console.error('Failed to send audio:', err);
        alert('Failed to send audio to server.');
      })
      .finally(function () {
        micBtn.classList.remove('processing');
        micBtn.title = 'Voice dictation';
      });
  }
})();

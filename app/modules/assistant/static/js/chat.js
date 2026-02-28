/**
 * Chat client with streaming for AI Psychologist.
 * History is persisted server-side (ChatMessage model).
 * Handles <think>...</think> blocks as collapsible sections.
 */
(function () {
  var messagesDiv = document.getElementById('chat-messages');
  var inputEl = document.getElementById('chat-input');
  var sendBtn = document.getElementById('chat-send-btn');
  var statusEl = document.getElementById('chat-status');

  var isStreaming = false;
  var thinkOpenState = new WeakMap();

  // Scroll to bottom on load
  messagesDiv.scrollTop = messagesDiv.scrollHeight;

  // Process existing assistant messages (render think blocks + markdown)
  var existingMsgs = messagesDiv.querySelectorAll('.chat-msg-assistant');
  for (var i = 0; i < existingMsgs.length; i++) {
    var raw = existingMsgs[i].textContent;
    renderAssistantMessage(existingMsgs[i], raw);
  }

  messagesDiv.addEventListener('toggle', function (e) {
    var target = e.target;
    if (!target || !target.classList || !target.classList.contains('think-block')) {
      return;
    }
    var container = target.closest('.chat-msg-assistant');
    if (!container) return;
    var state = getThinkState(container);
    var index = target.getAttribute('data-think-index');
    if (index === null) return;
    state[index] = target.open;
  }, true);

  sendBtn.addEventListener('click', sendMessage);
  inputEl.addEventListener('keydown', function (e) {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      sendMessage();
    }
  });

  // Toolbar buttons
  document.getElementById('btn-clear-chat').addEventListener('click', function () {
    if (!confirm('Clear all chat history?')) return;
    fetch('/assistant/clear-chat', { method: 'POST' })
      .then(function () { location.reload(); });
  });

  document.getElementById('btn-reindex').addEventListener('click', function () {
    if (!confirm('Reindex all diary entries? This may take a while.')) return;
    fetch('/assistant/reindex', { method: 'POST' })
      .then(function (r) { return r.json(); })
      .then(function (data) {
        statusEl.textContent = data.message || 'Reindexing...';
        pollStatus();
      });
  });

  document.getElementById('btn-reset-profile').addEventListener('click', function () {
    if (!confirm('Reset psychological profile? It will rebuild automatically.')) return;
    fetch('/assistant/reset-profile', { method: 'POST' })
      .then(function () {
        statusEl.textContent = 'Profile reset';
        setTimeout(function () { statusEl.textContent = ''; }, 3000);
      });
  });

  loadStatus();
  warmupModel();

  function loadStatus() {
    fetch('/assistant/status')
      .then(function (r) { return r.json(); })
      .then(function (data) {
        if (data.total_entries > 0) {
          var parts = [];
          if (data.llm_loading) {
            parts.push('model loading...');
          }
          parts.push(data.embedded + '/' + data.total_entries + ' embedded');
          parts.push(data.summarized + '/' + data.total_entries + ' summarized');
          if (data.profile_version > 0) {
            parts.push('profile v' + data.profile_version);
          }
          statusEl.textContent = parts.join(' · ');
        }
      })
      .catch(function () {});
  }

  function pollStatus() {
    var interval = setInterval(function () {
      fetch('/assistant/status')
        .then(function (r) { return r.json(); })
        .then(function (data) {
          var parts = [];
          if (data.llm_loading) {
            parts.push('model loading...');
          }
          parts.push(data.embedded + '/' + data.total_entries + ' embedded');
          parts.push(data.summarized + '/' + data.total_entries + ' summarized');
          statusEl.textContent = parts.join(' В· ');
          if (data.embedded >= data.total_entries && data.summarized >= data.total_entries) {
            statusEl.textContent = 'Reindex complete';
            clearInterval(interval);
            setTimeout(function () { loadStatus(); }, 3000);
          }
        });
    }, 5000);
  }

  function sendMessage() {
    var text = inputEl.value.trim();
    if (!text || isStreaming) return;

    appendMessage('user', text);
    inputEl.value = '';

    streamResponse(text);
  }

  function appendMessage(role, content) {
    var div = document.createElement('div');
    div.className = 'chat-msg chat-msg-' + role;
    div.textContent = content;
    messagesDiv.appendChild(div);
    messagesDiv.scrollTop = messagesDiv.scrollHeight;
    return div;
  }

  /**
   * Convert raw text with <think>...</think> to HTML with collapsible details.
   */
  function renderThinkBlocks(text) {
    var result = '';
    var remaining = text;
    var thinkIndex = 0;

    while (true) {
      var openIdx = remaining.indexOf('<think>');
      if (openIdx === -1) break;

      // Text before <think>
      result += renderMarkdown(remaining.substring(0, openIdx));

      var afterOpen = remaining.substring(openIdx + 7);
      var closeIdx = afterOpen.indexOf('</think>');

      if (closeIdx !== -1) {
        // Complete think block
        var thinkContent = afterOpen.substring(0, closeIdx);
        result += '<details class="think-block" data-think-index="' + thinkIndex + '"><summary>thought process</summary><div class="think-content">' +
          renderMarkdown(thinkContent) + '</div></details>';
        remaining = afterOpen.substring(closeIdx + 8);
        thinkIndex += 1;
      } else {
        // Unclosed think block (still streaming) — hide content for now
        var thinkContent = afterOpen;
        result += '<details class="think-block think-streaming" data-think-index="' + thinkIndex + '"><summary>thinking...</summary><div class="think-content">' +
          renderMarkdown(thinkContent) + '</div></details>';
        remaining = '';
        thinkIndex += 1;
      }
    }

    result += renderMarkdown(remaining);
    return result;
  }

  function warmupModel() {
    fetch('/assistant/warmup', { method: 'POST' })
      .catch(function () {});
  }

  function renderMarkdown(text) {
    initMarkdown();
    if (markdownLib) {
      return markdownLib.parse(text || '');
    }
    return formatInlineMarkdown(escapeHtml(text || ''));
  }

  function formatInlineMarkdown(text) {
    // Minimal fallback if marked is not available
    var formatted = text.replace(/\*\*([\s\S]+?)\*\*/g, '<strong>$1</strong>');
    formatted = formatted.replace(/__([\s\S]+?)__/g, '<strong>$1</strong>');
    formatted = formatted.replace(/`([^`]+)`/g, '<code>$1</code>');
    return formatted;
  }

  var markdownLib = null;
  var markdownReady = false;

  function initMarkdown() {
    if (markdownReady) return;
    markdownReady = true;
    if (!window.marked || typeof window.marked.parse !== 'function') {
      return;
    }

    markdownLib = window.marked;
    var renderer = new markdownLib.Renderer();

    renderer.html = function (html) {
      return escapeHtml(html);
    };

    renderer.link = function (href, title, text) {
      var safeHref = sanitizeUrl(href);
      if (!safeHref) {
        return text;
      }
      var titleAttr = title ? ' title="' + escapeHtml(title) + '"' : '';
      return '<a href="' + escapeHtml(safeHref) + '"' + titleAttr + ' rel="noopener noreferrer" target="_blank">' + text + '</a>';
    };

    renderer.image = function (href, title, text) {
      var safeHref = sanitizeUrl(href);
      if (!safeHref) {
        return escapeHtml(text || '');
      }
      var titleAttr = title ? ' title="' + escapeHtml(title) + '"' : '';
      var altText = escapeHtml(text || '');
      return '<img src="' + escapeHtml(safeHref) + '" alt="' + altText + '"' + titleAttr + '>';
    };

    markdownLib.setOptions({
      gfm: true,
      breaks: true,
      headerIds: false,
      mangle: false,
      renderer: renderer
    });
  }

  function sanitizeUrl(href) {
    if (!href) return '';
    var value = ('' + href).trim();
    if (!value) return '';
    var lower = value.toLowerCase();
    if (lower.startsWith('javascript:') || lower.startsWith('data:') || lower.startsWith('vbscript:')) {
      return '';
    }
    if (lower.startsWith('http://') || lower.startsWith('https://') || lower.startsWith('mailto:') || lower.startsWith('tel:')) {
      return value;
    }
    if (value.startsWith('/') || value.startsWith('#') || value.startsWith('./') || value.startsWith('../')) {
      return value;
    }
    return '';
  }

  function getThinkState(container) {
    var state = thinkOpenState.get(container);
    if (!state) {
      state = {};
      thinkOpenState.set(container, state);
    }
    return state;
  }

  function applyThinkOpenStates(container) {
    if (!container) return;
    var state = getThinkState(container);
    var blocks = container.querySelectorAll('details.think-block');
    for (var i = 0; i < blocks.length; i++) {
      var index = blocks[i].getAttribute('data-think-index');
      if (index !== null && Object.prototype.hasOwnProperty.call(state, index)) {
        blocks[i].open = state[index];
      }
    }
  }

  function renderAssistantMessage(container, text) {
    container.innerHTML = renderThinkBlocks(text);
    applyThinkOpenStates(container);
    if (container && container.dataset && container.dataset.continuation === '1') {
      var indicator = document.createElement('div');
      indicator.className = 'chat-continue-indicator';
      indicator.textContent = 'продолжение ответа...';
      container.appendChild(indicator);
    }
  }

  function escapeHtml(text) {
    var div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
  }

  function streamResponse(userMessage) {
    isStreaming = true;
    sendBtn.disabled = true;
    sendBtn.textContent = '...';

    var assistantDiv = appendMessage('assistant', '');
    var fullText = '';

    fetch('/assistant/stream', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ message: userMessage })
    })
      .then(function (response) {
        var reader = response.body.getReader();
        var decoder = new TextDecoder();
        var buffer = '';

        function read() {
          return reader.read().then(function (result) {
            if (result.done) {
              finish();
              return;
            }

            buffer += decoder.decode(result.value, { stream: true });

            var lines = buffer.split('\n');
            buffer = lines.pop();

            for (var i = 0; i < lines.length; i++) {
              var line = lines[i].trim();
              if (!line.startsWith('data: ')) continue;
              var payload = line.substring(6);

              if (payload === '[DONE]') {
                finish();
                return;
              }

              try {
                var data = JSON.parse(payload);
                if (data.token) {
                  fullText += data.token;
                  // Render with think block handling
                  renderAssistantMessage(assistantDiv, fullText);
                  messagesDiv.scrollTop = messagesDiv.scrollHeight;
                }
                if (data.event === 'continuation') {
                  assistantDiv.dataset.continuation = '1';
                  renderAssistantMessage(assistantDiv, fullText);
                  messagesDiv.scrollTop = messagesDiv.scrollHeight;
                }
                if (data.error) {
                  assistantDiv.textContent = 'Error: ' + data.error;
                  assistantDiv.classList.add('chat-msg-error');
                }
              } catch (e) {
                // ignore parse errors
              }
            }

            return read();
          });
        }

        return read();
      })
      .catch(function (err) {
        if (!fullText) {
          assistantDiv.textContent = 'Connection error. Is the model loaded?';
          assistantDiv.classList.add('chat-msg-error');
        }
        finish();
      });

    function finish() {
      isStreaming = false;
      sendBtn.disabled = false;
      sendBtn.textContent = 'Send';
      // Final render to ensure closed think blocks
      if (fullText) {
        if (assistantDiv.dataset) {
          delete assistantDiv.dataset.continuation;
        }
        renderAssistantMessage(assistantDiv, fullText);
      }
    }
  }
})();

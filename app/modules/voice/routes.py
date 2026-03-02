"""Voice transcription endpoint."""
import tempfile
import os
import sys
from pathlib import Path
from flask import request, jsonify
from . import bp

# Lazy-loaded whisper model (stays in memory after first use)
_model = None


def _get_model():
    global _model
    if _model is None:
        # In frozen exe, torch may fail to fully initialize (DLL/stdlib issues)
        # leaving a broken partial module in sys.modules.  CTranslate2 (used by
        # faster_whisper) imports torch optionally — a clean ImportError is fine,
        # but a partial module causes "has no attribute 'autograd'" errors.
        # Pre-test torch and clean up if it fails, so ctranslate2 skips it.
        if getattr(sys, 'frozen', False) and 'torch' not in sys.modules:
            try:
                import torch  # noqa: F401
            except Exception:
                for key in [k for k in sys.modules if k == 'torch' or k.startswith('torch.')]:
                    del sys.modules[key]

        from faster_whisper import WhisperModel

        model_dir = Path(__file__).parent / 'models'
        # Check if model files exist locally, otherwise download 'small'
        model_bin = model_dir / 'model.bin'
        if model_bin.exists():
            model_path = str(model_dir)
        else:
            # Fall back to downloading the model on first use
            model_path = 'small'

        _model = WhisperModel(
            model_path,
            device='cpu',
            compute_type='int8',
            download_root=str(model_dir)
        )
    return _model


@bp.route('/transcribe', methods=['POST'])
def transcribe():
    """Receive audio blob, transcribe with Whisper, return text."""
    if 'audio' not in request.files:
        return jsonify({'error': 'No audio file'}), 400

    audio_file = request.files['audio']

    with tempfile.NamedTemporaryFile(suffix='.webm', delete=False) as tmp:
        audio_file.save(tmp.name)
        tmp_path = tmp.name

    try:
        model = _get_model()
        segments, info = model.transcribe(
            tmp_path,
            language='ru',
            beam_size=5,
            vad_filter=True
        )
        text = ' '.join(segment.text.strip() for segment in segments)

        if not text.strip():
            segments, info = model.transcribe(
                tmp_path,
                language='ru',
                beam_size=5,
                vad_filter=False
            )
            text = ' '.join(segment.text.strip() for segment in segments)
        return jsonify({'text': text, 'language': info.language})
    except Exception as e:
        return jsonify({'error': str(e)}), 500
    finally:
        os.unlink(tmp_path)

# Voice Dictation Model

Download the Whisper "small" model for CTranslate2.

## Option 1: Automatic (recommended)

The model will be downloaded automatically on first use.
Just start the app and press the microphone button.

## Option 2: Manual download

```bash
pip install faster-whisper
python -c "from faster_whisper import WhisperModel; WhisperModel('small', download_root='.')"
```

Place all model files (model.bin, config.json, tokenizer.json, etc.) in this directory.

## Better Russian accuracy

For better quality, use the "medium" model (~1.5GB RAM):

```bash
python -c "from faster_whisper import WhisperModel; WhisperModel('medium', download_root='.')"
```

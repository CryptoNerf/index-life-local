# AI Psychologist Model

Place a GGUF model file in this directory.
The module will automatically use the first .gguf file it finds.

## Recommended: Qwen3-8B Instruct (Q4_K_M) — ~5 GB

Best balance of quality, Russian language support, and hardware requirements.
Runs on M1 16GB, RTX 2060+, or any system with 16GB RAM.

### Download

```bash
pip install huggingface-hub
huggingface-cli download bartowski/Qwen_Qwen3-8B-GGUF Qwen3-8B-Q4_K_M.gguf --local-dir .
```

## Alternative: Qwen3-14B Instruct (Q4_K_M) — ~9 GB

Higher quality, needs 16GB+ RAM. Good for M1 16GB (at shorter context) or RTX 3060 12GB.

```bash
huggingface-cli download bartowski/Qwen_Qwen3-14B-GGUF Qwen3-14B-Q4_K_M.gguf --local-dir .
```

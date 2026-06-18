# index.life — Local mood diary
# https://github.com/CryptoNerf/index-life-local
# Copyright (C) 2026 Émile Alexanyan
#
# Licensed under AGPL-3.0 with additional terms per Section 7
# (preservation of author attribution, no misrepresentation of
# origin). See LICENSE and COPYRIGHT at the root of this project.
"""Shared text helpers for the LLM-backed modules.

`strip_think`, `count_tokens` and `truncate_to_tokens` were copy-pasted
across assistant/memory.py, assistant/routes.py and deep_mind/analysis.py.
The copies had already started to drift: the two `truncate_to_tokens`
versions kept *opposite* ends of the text (memory kept the tail — the most
recent summaries; routes kept the head — the start of a prompt being
trimmed to fit). Centralising them here removes the duplication and makes
that head/tail choice an explicit, visible argument instead of a hidden
divergence between two look-alike functions.

Only the stdlib `re` is imported, so this module is safe to import even
when the heavy LLM dependencies (llama_cpp, numpy) are not available.
"""
import re


def strip_think(text: str) -> str:
    """Remove ``<think>…</think>`` reasoning blocks from model output.

    Handles a normal closed block, a trailing unclosed ``<think>`` (the
    model ran out of tokens mid-thought), and any stray closing tags.
    """
    if not text:
        return ''
    cleaned = re.sub(r'(?is)<think>.*?</think>', '', text)
    cleaned = re.sub(r'(?is)<think>.*$', '', cleaned)
    cleaned = re.sub(r'(?is)</think>', '', cleaned)
    return cleaned.strip()


def count_tokens(llm, text: str) -> int:
    """Token count via the model's tokenizer, with a ~4-chars/token fallback
    when the model can't be reached (or hasn't been loaded yet)."""
    try:
        tokens = llm.tokenize(text.encode('utf-8'))
        return len(tokens)
    except Exception:
        return max(1, len(text) // 4)


def truncate_to_tokens(llm, text: str, max_tokens: int, *, keep: str = 'head') -> str:
    """Trim ``text`` to at most ``max_tokens`` tokens.

    ``keep='head'`` keeps the beginning — used when shrinking a prompt or a
    single message so it fits the context window. ``keep='tail'`` keeps the
    end — used when retaining the most recent material (e.g. the latest
    diary summaries feeding the psychological profile).

    Falls back to a ~4-chars/token character slice (from the same end) if
    tokenizing/detokenizing fails.
    """
    if max_tokens <= 0:
        return ''
    try:
        tokens = llm.tokenize(text.encode('utf-8'))
        if len(tokens) <= max_tokens:
            return text
        token_slice = tokens[:max_tokens] if keep == 'head' else tokens[-max_tokens:]
        truncated = llm.detokenize(token_slice)
        if isinstance(truncated, bytes):
            return truncated.decode('utf-8', errors='ignore')
        if isinstance(truncated, str):
            return truncated
    except Exception:
        pass
    approx_chars = max(0, max_tokens * 4)
    return text[:approx_chars] if keep == 'head' else text[-approx_chars:]

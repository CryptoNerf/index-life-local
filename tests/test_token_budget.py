"""Tests for the LLM context-window accounting in the assistant routes.

These functions decide what gets sent to a fixed-size context window —
get them wrong and the native llama.cpp call either truncates the user's
question or crashes on overflow. They take the `llm` as a parameter, so
we drive them with a tiny deterministic stub instead of loading a model.

`FakeLLM` tokenizes 1 token per UTF-8 byte (so for ASCII, tokens == chars),
which makes every budget assertion below exact and easy to reason about.
"""
import pytest

from app.modules.assistant import routes


class FakeLLM:
    def tokenize(self, data: bytes):
        return list(data)            # one int per byte

    def detokenize(self, tokens):
        return bytes(tokens)


class BrokenLLM:
    def tokenize(self, data: bytes):
        raise RuntimeError('no tokenizer')


# ── terminal-punctuation detection ────────────────────────────

@pytest.mark.parametrize('text,expected', [
    ('Done.', True),
    ('Really?', True),
    ('Stop!', True),
    ('trailing ellipsis…', True),
    ('an unfinished clause', False),
    ('', True),                      # empty == nothing left to finish
    ('Сделано.', True),
    ('продолжается', False),
])
def test_ends_with_terminal_punct(text, expected):
    assert routes._ends_with_terminal_punct(text) is expected


# ── token counting ────────────────────────────────────────────

def test_count_tokens_uses_model_tokenizer():
    assert routes._count_tokens(FakeLLM(), 'abcde') == 5


def test_count_tokens_falls_back_when_tokenizer_breaks():
    # Fallback is len // 4, floored at 1.
    assert routes._count_tokens(BrokenLLM(), 'a' * 8) == 2
    assert routes._count_tokens(BrokenLLM(), '') == 1


# ── truncation ────────────────────────────────────────────────

def test_truncate_keeps_text_within_budget():
    assert routes._truncate_to_tokens(FakeLLM(), 'abcdef', 3) == 'abc'


def test_truncate_noop_when_already_short():
    assert routes._truncate_to_tokens(FakeLLM(), 'abc', 10) == 'abc'


def test_truncate_to_zero_is_empty():
    assert routes._truncate_to_tokens(FakeLLM(), 'abc', 0) == ''


# ── continuation heuristic ────────────────────────────────────

def test_needs_continuation_true_when_long_unfinished_and_near_limit(monkeypatch):
    monkeypatch.setenv('LLM_RESERVE_TOKENS', '20')   # threshold = max(64, 12) = 64
    # 70 tokens, no terminal punctuation → likely hit the length cap.
    assert routes._needs_continuation(FakeLLM(), 'a' * 70) is True


def test_no_continuation_when_finished(monkeypatch):
    monkeypatch.setenv('LLM_RESERVE_TOKENS', '20')
    assert routes._needs_continuation(FakeLLM(), 'a' * 70 + '.') is False


def test_no_continuation_when_short(monkeypatch):
    monkeypatch.setenv('LLM_RESERVE_TOKENS', '20')
    assert routes._needs_continuation(FakeLLM(), 'a' * 50) is False    # 50 < 64
    assert routes._needs_continuation(FakeLLM(), 'short') is False     # < 40 chars


# ── full message-list trimming ────────────────────────────────

def test_trim_drops_oldest_history_but_keeps_system_and_last(monkeypatch):
    # budget = n_ctx - reserve - 8 = 80 - 8 - 8 = 64. msg cost = content + 4.
    monkeypatch.setattr(routes, '_llm_n_ctx', 80)
    monkeypatch.setenv('LLM_RESERVE_TOKENS', '8')

    messages = [
        {'role': 'system', 'content': 'S' * 6},     # 10
        {'role': 'user', 'content': 'B' * 30},      # 34  (oldest — should drop)
        {'role': 'assistant', 'content': 'A' * 30},  # 34  (should survive)
        {'role': 'user', 'content': 'L' * 10},      # 14  (current turn — must stay)
    ]

    out = routes._trim_messages_to_fit(FakeLLM(), messages)

    assert out[0]['role'] == 'system'
    assert out[-1]['content'] == 'L' * 10           # current turn preserved
    contents = [m['content'] for m in out]
    assert 'B' * 30 not in contents                 # oldest evicted
    assert 'A' * 30 in contents
    # Everything that remains fits the budget.
    total = sum(routes._count_tokens(FakeLLM(), m['content']) + 4 for m in out)
    assert total <= 64


def test_trim_empty_list_is_noop():
    assert routes._trim_messages_to_fit(FakeLLM(), []) == []

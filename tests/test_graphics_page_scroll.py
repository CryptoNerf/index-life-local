"""The person page keeps its silhouette in view while the notes scroll.

The figure is position: sticky, and it never stuck: graphics.css set
overflow on both html and body, which turns body into a scroll container
of its own that never scrolls (the viewport does), so the figure had
nothing to stick to and scrolled away with a hundred notes. Checked in the
stylesheet because the failure is purely a CSS one.
"""
import re
from pathlib import Path

CSS = (Path(__file__).resolve().parents[1]
       / 'app' / 'modules' / 'graphics' / 'static' / 'css' / 'graphics.css').read_text(encoding='utf-8')


def _rule(selector):
    m = re.search(r'(?m)^' + re.escape(selector) + r'\s*\{([^}]*)\}', CSS)
    assert m, selector
    return m.group(1)


def test_only_the_root_scrolls():
    assert 'overflow: auto' in _rule('html')
    assert 'overflow: visible' in _rule('body')


def test_html_and_body_are_not_given_overflow_together():
    assert not re.search(r'html\s*,\s*body\s*\{[^}]*overflow\s*:\s*(auto|scroll|hidden)', CSS)

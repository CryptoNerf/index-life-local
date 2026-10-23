"""The day editor in a real browser: quoting, spacing, and what gets saved.

Quoting used to take whole paragraphs. A note written line by line is one
paragraph with line breaks, so selecting one line and pressing the quote
button quoted the whole note; a fragment of a sentence quoted the whole
paragraph. These tests select text the way a user does and check the
Markdown that would be saved.

Opt-in, since they need Chrome: INDEXLIFE_BROWSER_TESTS=1 pytest tests/browser
"""
import json
import os
import time

import pytest

from ._cdp import chrome_path
from .test_customization_previews import browser, demo  # noqa: F401 (fixtures)

pytestmark = pytest.mark.skipif(
    not (os.environ.get('INDEXLIFE_BROWSER_TESTS') and chrome_path()),
    reason='browser tests are opt-in (INDEXLIFE_BROWSER_TESTS=1) and need Chrome')

DAY = '2026-09-26'


class Editor:
    def __init__(self, browser, base):
        self.b = browser
        self.b.goto(f'{base}/day/{DAY}', settle=1.0)
        self.b.js('localStorage.clear(); true')

    def load(self, markdown):
        self.b.js(f'tiptapEditor.commands.setContent({json.dumps(markdown)}); true')
        time.sleep(0.6)   # a separate undo step from what follows

    def markdown(self):
        return self.b.js('tiptapEditor.storage.markdown.getMarkdown()')

    def select(self, text, start_offset=0, end_offset=None):
        """Select `text` (or a cursor at `start_offset` into it if end_offset == start_offset)."""
        return self.b.js(f"""(() => {{
          const want = {json.dumps(text)}; let at = null;
          tiptapEditor.state.doc.descendants((n, pos) => {{
            if (at === null && n.isText && n.text.includes(want)) at = pos + n.text.indexOf(want); }});
          if (at === null) throw new Error('not found: ' + want);
          const end = {json.dumps(end_offset)};
          tiptapEditor.commands.setTextSelection({{from: at + {start_offset},
                                                   to: at + (end === null ? want.length : end)}});
          return true; }})()""")

    def quote(self):
        self.b.js("document.querySelector('[data-format=quote]').click(); true")
        return self.markdown()


@pytest.fixture
def editor(demo, browser):  # noqa: F811
    return Editor(browser, demo())


LINES = 'Первая строка\nВторая строка\nТретья строка'


def test_one_line_of_a_line_by_line_note(editor):
    editor.load(LINES)
    editor.select('Вторая строка')
    assert editor.quote() == 'Первая строка\n\n> Вторая строка\n\nТретья строка'


def test_the_cursor_alone_quotes_its_line(editor):
    editor.load(LINES)
    editor.select('Вторая строка', 3, 3)
    assert editor.quote() == 'Первая строка\n\n> Вторая строка\n\nТретья строка'


def test_a_fragment_of_a_sentence_is_quoted_as_selected(editor):
    editor.load('Утром было тихо. Потом позвонила мама и сказала важное.\n\nВечером гулял.')
    editor.select('Потом позвонила мама и сказала важное.')
    assert editor.quote() == ('Утром было тихо.\n\n> Потом позвонила мама и сказала важное.'
                              '\n\nВечером гулял.')


def test_a_whole_paragraph_and_a_selection_over_a_line_break(editor):
    editor.load('Один.\n\nДва целиком.\n\nТри.')
    editor.select('Два целиком.')
    assert editor.quote() == 'Один.\n\n> Два целиком.\n\nТри.'
    # Starting at the end of the line above, across the break.
    editor.load(LINES)
    editor.b.js("""(() => { let a = null, z = null;
      tiptapEditor.state.doc.descendants((n, p) => { if (!n.isText) return;
        if (n.text === 'Первая строка') a = p + n.text.length;
        if (n.text === 'Вторая строка') z = p + n.text.length; });
      tiptapEditor.commands.setTextSelection({from: a, to: z}); return true; })()""")
    assert editor.quote() == 'Первая строка\n\n> Вторая строка\n\nТретья строка'


def test_the_keyboard_shortcut_quotes_the_same_way(editor):
    editor.load(LINES)
    editor.select('Вторая строка')
    editor.b.js("""(() => { tiptapEditor.view.someProp('handleKeyDown', f => f(tiptapEditor.view,
      new KeyboardEvent('keydown', {code: 'KeyB', key: 'B', ctrlKey: true, shiftKey: true})));
      return true; })()""")
    assert editor.markdown() == 'Первая строка\n\n> Вторая строка\n\nТретья строка'


def test_unquoting_one_line_leaves_the_rest_quoted(editor):
    editor.load('> Строка А\n> Строка Б\n> Строка В')
    editor.select('Строка Б')
    assert editor.quote() == '> Строка А\n\nСтрока Б\n\n> Строка В'


def test_a_list_is_quoted_whole(editor):
    editor.load('- пункт один\n- пункт два')
    editor.select('пункт два')
    assert editor.quote() == '> - пункт один\n> - пункт два'


def test_undo_takes_back_the_quote_only(editor):
    editor.load(LINES)
    editor.select('Вторая строка')
    editor.quote()
    editor.b.js('tiptapEditor.commands.undo(); true')
    assert editor.markdown().replace('\\\n', '\n') == LINES


def test_what_is_saved_reads_back_the_same(editor):
    rich = ('# Заголовок\n\nАбзац один.\nСтрока два.\n\n> Цитата\n> вторая строка\n\n'
            'После цитаты.\n\n- пункт\n- пункт\n\n1. раз\n2. два\n\n---\n\n## Ещё\n\nТекст.')
    editor.load(rich)
    first = editor.markdown()
    editor.load(first)
    assert editor.markdown() == first


def test_spacing_rhythm(editor):
    editor.load('# Заголовок\n\nАбзац.\nСтрока того же абзаца.\n\nНовый абзац.\n\n'
                '> Цитата\n\n- а\n- б\n\n1. в\n2. г\n\n## Подзаголовок\n\nТекст.')
    m = json.loads(editor.b.js("""(() => {
      const pm = document.querySelector('.ProseMirror');
      const box = (el) => el.getBoundingClientRect();
      const ps = pm.querySelectorAll(':scope > p');
      const lh = parseFloat(getComputedStyle(ps[0]).lineHeight);
      const q = pm.querySelector('blockquote'), qp = q.querySelector('p');
      const lists = pm.querySelectorAll(':scope > ul, :scope > ol');
      const h2 = pm.querySelector('h2');
      return JSON.stringify({
        lineHeight: lh,
        paraGap: box(ps[1]).top - box(ps[0]).bottom,
        quoteInnerTop: box(qp).top - box(q).top,
        quoteInnerBottom: box(q).bottom - box(qp).bottom,
        listGap: box(lists[1]).top - box(lists[0]).bottom,
        h2Above: box(h2).top - box(h2.previousElementSibling).bottom,
        h2Below: box(h2.nextElementSibling).top - box(h2).bottom,
      }); })()"""))
    # A new paragraph is visibly more than a line break, and no gulf.
    assert 0.35 * m['lineHeight'] <= m['paraGap'] <= 0.8 * m['lineHeight'], m
    # The quote's padding is its only inner space, the same top and bottom.
    assert abs(m['quoteInnerTop'] - m['quoteInnerBottom']) < 1 and m['quoteInnerTop'] < 12, m
    # Two lists in a row are two lists.
    assert m['listGap'] >= m['paraGap'] - 1, m
    # A heading sits with its text.
    assert m['h2Below'] < m['h2Above'] / 2, m


def test_the_box_grows_and_the_toolbar_stays_in_reach(editor):
    editor.load('\n\n'.join(f'Абзац номер {i}, довольно длинный, чтобы занять строку.'
                            for i in range(40)))
    inner = json.loads(editor.b.js("""JSON.stringify((() => {
      const ed = document.querySelector('.tiptap-editor');
      return [ed.scrollHeight, ed.clientHeight]; })())"""))
    assert inner[0] <= inner[1] + 1, 'the note scrolls inside its own box'
    editor.b.js("window.scrollTo(0, document.body.scrollHeight / 2); true")
    time.sleep(0.2)
    top = editor.b.js("document.querySelector('.formatting-toolbar').getBoundingClientRect().top")
    assert -1 <= top <= 1, top


def test_typed_quotes_are_russian(editor):
    editor.load('')
    editor.b.js("""(() => { tiptapEditor.commands.focus();
      for (const ch of '"привет"') tiptapEditor.view.someProp('handleTextInput',
        f => f(tiptapEditor.view, tiptapEditor.state.selection.from,
               tiptapEditor.state.selection.to, ch)) || tiptapEditor.commands.insertContent(ch);
      return true; })()""")
    assert editor.markdown() == '«привет»'

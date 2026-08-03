"""The editor writes colour and fill as inline HTML; everything that reads a
note as text must see the words, not the markup."""
import pytest

from app.note_text import plain_text


@pytest.mark.parametrize('raw,expected', [
    ('<span style="color: rgb(192, 57, 43)">Плохой день</span>, но вечер норм',
     'Плохой день, но вечер норм'),
    ('<span style="background-color: #e0c14a">важное</span>', 'важное'),
    ('<mark>подсветка</mark> внутри', 'подсветка внутри'),
    ('обычная заметка', 'обычная заметка'),
    ('a &lt; b и b &gt; c', 'a < b и b > c'),      # entities decoded
    ('', ''),
    (None, ''),
])
def test_plain_text(raw, expected):
    assert plain_text(raw) == expected


def test_leaves_text_that_only_looks_like_markup():
    """Only the editor's own span/mark wrappers go — a person writing `<3`
    or pasting a snippet on purpose keeps what they wrote."""
    note = 'люблю <3 и <b>жирный</b> текст'
    assert plain_text(note) == note

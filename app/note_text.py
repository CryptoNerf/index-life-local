"""Reading a note as plain text.

The day editor stores notes as Markdown, and Markdown has no notion of text
colour or a background fill — so those two marks are written as inline HTML
(`<span style="color: …">`), and the serialiser escapes stray angle brackets
along the way.

That is right for the editor and wrong everywhere else: the graphics pages
show notes as text, and the assistant feeds them to a model. Both want the
words, not the markup. `plain_text()` is the one place that strips it.
"""

import html
import re

# Only the two tags the editor itself emits. Anything else a person typed in
# their note — `<3`, `a <b>` in prose, an HTML snippet they pasted on purpose —
# is left exactly as written.
_STYLE_TAG_RE = re.compile(r'</?(?:span|mark)\b[^>]*>', re.IGNORECASE)


def plain_text(note) -> str:
    """A note with the colour/fill markup removed and entities decoded."""
    if not note:
        return ''
    return html.unescape(_STYLE_TAG_RE.sub('', str(note)))

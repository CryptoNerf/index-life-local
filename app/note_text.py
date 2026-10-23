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
    text = html.unescape(_STYLE_TAG_RE.sub('', str(note)))
    # Plain text has no blocks to protect: every hard break is a newline.
    return re.sub(r'(?<!\\)\\\n', '\n', text)


# ── line breaks inside a paragraph ────────────────────────────

# The editor writes a line break inside a paragraph (Shift+Enter, or a plain
# newline in a note written on the phone) as Markdown's "backslash, newline".
# Notes are read with single newlines as breaks, so the backslash is only
# needed where the next line would otherwise start a block of its own: a
# heading, a list item, a quote, a rule, a fence. Everywhere else it was
# noise: it showed on the phone, in search results and in what the AI read.
_BLOCK_START = re.compile(
    r'\s{0,3}(?:#{1,6}(?:\s|$)|>|[*+-](?:\s|$)|\d{1,9}[.)](?:\s|$)'
    r'|```|~~~|[-=]+\s*$|\*{3,}\s*$|_{3,}\s*$)')
_QUOTE_PREFIX = re.compile(r'^(?:\s{0,3}>\s?)+')


def soften_hard_breaks(markdown: str) -> str:
    """Drop the backslash of a hard line break wherever a plain newline
    means the same thing. Code fences are left alone."""
    if not markdown or '\\\n' not in markdown:
        return markdown or ''
    lines = markdown.split('\n')
    out = []
    in_fence = False
    for i, line in enumerate(lines):
        if line.lstrip().startswith(('```', '~~~')):
            in_fence = not in_fence
        trailing = len(line) - len(line.rstrip('\\'))
        if (not in_fence and trailing % 2 == 1 and i + 1 < len(lines)):
            nxt = lines[i + 1]
            prefix = _QUOTE_PREFIX.match(line)
            prefix = prefix.group(0) if prefix else ''
            rest = nxt
            if prefix:
                # Inside a quote the next line repeats the ">" marker; what
                # matters is what follows it.
                nprefix = _QUOTE_PREFIX.match(nxt)
                if nprefix and nprefix.group(0).count('>') == prefix.count('>'):
                    rest = nxt[nprefix.end():]
            if rest.strip() and not _BLOCK_START.match(rest):
                line = line[:-1]
        out.append(line)
    return '\n'.join(out)

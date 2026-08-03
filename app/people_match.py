"""AI-free person-mention matching for the "My people" graph.

Matches a tracked name across all of its Russian declined forms by lemma
(pymorphy3), so adding "Аня" also finds "Ане", "Аню", "Аней", "Ани"… No AI and
no network — pure morphology over the note text. Deliberately has NO tone/rating:
the day's mood is never attributed to a person.
"""
import json
import re
import threading

_WORD_RE = re.compile(r'\w+', re.UNICODE)

_morph = None
_morph_failed = False
_morph_lock = threading.Lock()

# Cache each entry's lemma-set so a page with many tracked people re-uses one
# lemmatization per note instead of redoing it per person. Invalidated when the
# note's updated_at changes.
_entry_cache = {}          # entry_id -> (updated_at_iso, frozenset[str])
_cache_lock = threading.Lock()
_lemma_cache = {}          # word -> lemma (bounded below)


def _get_morph():
    """The pymorphy3 analyzer, or None if it can't load (then matching falls
    back to plain lowercased words — no declensions, but never crashes)."""
    global _morph, _morph_failed
    if _morph is not None:
        return _morph
    if _morph_failed:
        return None
    with _morph_lock:
        if _morph is not None:
            return _morph
        if _morph_failed:
            return None
        try:
            import pymorphy3
            _morph = pymorphy3.MorphAnalyzer()
        except Exception:
            _morph_failed = True
            return None
    return _morph


def _lemma(word: str) -> str:
    cached = _lemma_cache.get(word)
    if cached is not None:
        return cached
    morph = _get_morph()
    try:
        lemma = morph.parse(word)[0].normal_form if morph is not None else word
    except Exception:
        lemma = word
    if len(_lemma_cache) < 100000:
        _lemma_cache[word] = lemma
    return lemma


def _lemmas_of(text: str) -> set:
    return {_lemma(w) for w in _WORD_RE.findall((text or '').lower())}


def _json_list(raw) -> list:
    if not raw:
        return []
    try:
        value = json.loads(raw)
        return [str(x) for x in value] if isinstance(value, list) else []
    except Exception:
        return []


def entry_lemmas(entry) -> frozenset:
    """Lemma-set of an entry's note, cached by (id, updated_at)."""
    stamp = entry.updated_at.isoformat() if entry.updated_at else ''
    cached = _entry_cache.get(entry.id)
    if cached and cached[0] == stamp:
        return cached[1]
    lemmas = frozenset(_lemmas_of(entry.note))
    with _cache_lock:
        _entry_cache[entry.id] = (stamp, lemmas)
    return lemmas


def match_lemmas(person) -> set:
    """Lemmas that count as a mention of this person (name + aliases − exclusions)."""
    lemmas = set()
    for term in [person.name] + _json_list(person.aliases):
        lemmas |= _lemmas_of(term)
    for term in _json_list(person.excluded):
        lemmas -= _lemmas_of(term)
    lemmas.discard('')
    return lemmas


def name_forms(name: str) -> list:
    """All declined forms of a single name — shown to the user so they can see
    what will be matched (and add/exclude as needed)."""
    try:
        parsed = _get_morph().parse(name)[0]
        return sorted({f.word for f in parsed.lexeme})
    except Exception:
        return [name.lower()]


def matching_entry_ids(person, entries) -> list:
    """IDs of `entries` whose note mentions this person (any matching lemma)."""
    wanted = match_lemmas(person)
    if not wanted:
        return []
    return [e.id for e in entries if wanted & entry_lemmas(e)]


def mention_spans(person, text) -> list:
    """(start, end) offsets of every word in `text` that counts as a mention.

    Same lemma test as `matching_entry_ids`, so what gets highlighted in a note
    is exactly what made the note match in the first place — including declined
    forms ("с Машей" for Маша) and aliases, minus the excluded words.
    """
    wanted = match_lemmas(person)
    if not wanted or not text:
        return []
    return [(m.start(), m.end()) for m in _WORD_RE.finditer(text)
            if _lemma(m.group(0).lower()) in wanted]


def highlight_segments(person, text) -> list:
    """`text` split into {'text': str, 'hit': bool} pieces for templates.

    Returning segments rather than HTML keeps the note escaped by Jinja: a
    diary entry may contain anything, and it is rendered as plain text.
    """
    text = text or ''
    spans = mention_spans(person, text)
    if not spans:
        return [{'text': text, 'hit': False}] if text else []
    out, pos = [], 0
    for start, end in spans:
        if start > pos:
            out.append({'text': text[pos:start], 'hit': False})
        out.append({'text': text[start:end], 'hit': True})
        pos = end
    if pos < len(text):
        out.append({'text': text[pos:], 'hit': False})
    return out


def mention_count(person, entries) -> int:
    return len(matching_entry_ids(person, entries))


_suggest_cache = None  # (signature, [names]) — recomputed only when entries change


def suggest_names(entries, limit: int = 40) -> list:
    """Candidate names found in the notes — words pymorphy tags as a first name,
    surname or patronymic — most frequent first. Feeds the "add person"
    autocomplete. Cached until entries change; [] if morphology is unavailable.
    """
    global _suggest_cache
    sig = (len(entries),
           max((e.updated_at.isoformat() for e in entries if e.updated_at), default=''))
    if _suggest_cache is not None and _suggest_cache[0] == sig:
        return _suggest_cache[1]

    from collections import Counter
    morph = _get_morph()
    counts = Counter()
    if morph is not None:
        name_tags = {'Name', 'Surn', 'Patr'}
        for entry in entries:
            for word in _WORD_RE.findall(entry.note or ''):
                if len(word) < 3 or word[0].islower():
                    continue  # only capitalised tokens are plausible proper nouns
                try:
                    for parse in morph.parse(word):
                        if name_tags & set(parse.tag.grammemes):
                            counts[parse.normal_form.capitalize()] += 1
                            break
                except Exception:
                    pass
    result = [name for name, _ in counts.most_common(limit)]
    _suggest_cache = (sig, result)
    return result

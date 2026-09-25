# index.life — Local mood diary
# https://github.com/CryptoNerf/index-life-local
# Copyright (C) 2026 Émile Alexanyan
#
# Licensed under AGPL-3.0 with additional terms per Section 7
# (preservation of author attribution, no misrepresentation of
# origin). See LICENSE and COPYRIGHT at the root of this project.
"""Forgetting what was derived from a day's text once that text is gone.

The assistant indexes each entry: a summary, a search vector, the people
and activities it mentions, the topic it belongs to on the neural map. A
local edit rebuilds all of that on save. A change that arrives through sync
did not — the pending-work scans only look for entries with *no* index — so
a day rewritten on the phone kept answering questions with what it used to
say, and a day deleted on the phone kept feeding the summaries and profile.

Dropping the rows is enough: every scan that fills the index treats an entry
without them as new work.
"""
from app import db
from app.models import (EntryActivity, EntryEmbedding, EntryIndexMark,
                        EntryPerson, EntrySummary, MindClusterEntry)

_DERIVED = (EntrySummary, EntryEmbedding, EntryPerson, EntryActivity,
            EntryIndexMark, MindClusterEntry)


def forget_derived(entry_ids) -> None:
    """Delete everything indexed from these entries. The caller commits."""
    ids = [i for i in set(entry_ids) if i is not None]
    if not ids:
        return
    for model in _DERIVED:
        (model.query
         .filter(model.entry_id.in_(ids))
         .delete(synchronize_session=False))

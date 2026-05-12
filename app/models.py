"""
Database models for local diary application
Single-user version (no authentication needed)
"""
import uuid as _uuid
from datetime import datetime

from app import db


def _new_uuid() -> str:
    return str(_uuid.uuid4())


class MoodEntry(db.Model):
    """Daily mood entry with rating and notes"""
    __tablename__ = 'mood_entries'

    id = db.Column(db.Integer, primary_key=True)
    date = db.Column(db.Date, nullable=False, unique=True, index=True)
    rating = db.Column(db.Integer, nullable=False)  # 1-10 scale
    note = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    # Sync fields
    uuid = db.Column(db.String(36), unique=True, index=True, default=_new_uuid)
    device_id = db.Column(db.String(36), nullable=True)
    deleted = db.Column(db.Boolean, default=False)

    def __repr__(self):
        return f'<MoodEntry {self.date}: {self.rating}/10>'

    def to_dict(self):
        """Convert to dictionary for JSON serialization"""
        return {
            'id': self.id,
            'date': self.date.isoformat(),
            'rating': self.rating,
            'note': self.note,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None
        }


class UserProfile(db.Model):
    """User profile (single user) with settings and photo"""
    __tablename__ = 'user_profile'

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(100), nullable=False, default='User')
    email = db.Column(db.String(120), nullable=True)
    photo_filename = db.Column(db.String(255), nullable=True)
    birthdate = db.Column(db.Date, nullable=True)
    # ISO 639-1 two-letter code. Drives the i18n context processor.
    # Migration v7 backfills 'ru' for existing rows.
    language = db.Column(db.String(2), nullable=False, default='ru')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def __repr__(self):
        return f'<UserProfile {self.username}>'

    @property
    def avg_rating(self):
        """Calculate average mood rating"""
        entries = MoodEntry.query.all()
        if not entries:
            return 0
        total = sum(entry.rating for entry in entries)
        return round(total / len(entries), 1)

    @property
    def total_entries(self):
        """Count total mood entries"""
        return MoodEntry.query.count()

    def to_dict(self):
        """Convert to dictionary"""
        return {
            'username': self.username,
            'email': self.email,
            'photo_filename': self.photo_filename,
            'avg_rating': self.avg_rating,
            'total_entries': self.total_entries
        }


# ── AI Psychologist memory layers ──────────────────────────────

class EntrySummary(db.Model):
    """Layer 3: short summary of each diary entry"""
    __tablename__ = 'entry_summaries'

    id = db.Column(db.Integer, primary_key=True)
    entry_id = db.Column(db.Integer, db.ForeignKey('mood_entries.id'), unique=True, index=True)
    summary = db.Column(db.Text)
    themes = db.Column(db.Text)  # JSON list: ["работа", "тревога"]
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    entry = db.relationship('MoodEntry', backref=db.backref('summary_obj', uselist=False))


class PersonAlias(db.Model):
    """User-defined mapping `alias → canonical` for the people chart.

    The 9B LLM occasionally produces multiple inflected/clipped forms for
    the same person ("Марь" instead of "Мари", "Дарёная" instead of
    "Дарёна") across different entries. Rather than guessing similarity
    automatically (frequency-based merging is unreliable), we let the
    user explicitly say "X is the same person as Y" and persist that
    decision. Aggregation in /insights/people walks aliases at chart
    render time, so existing entry_people rows don't need rewriting.
    """
    __tablename__ = 'person_aliases'

    id = db.Column(db.Integer, primary_key=True)
    alias = db.Column(db.String(100), nullable=False, unique=True, index=True)
    canonical = db.Column(db.String(100), nullable=False, index=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class EntryActivity(db.Model):
    """Canonical activity label extracted from an entry via LLM.

    One row per (entry, activity) — "ran + read + met friends" on one day
    produces three rows. The LLM is asked for short canonical labels
    ("спорт", "программирование", "встреча с друзьями") so similar actions
    across days naturally group. Aggregation joins back to MoodEntry to
    compute each activity's mood correlation.
    """
    __tablename__ = 'entry_activities'

    id = db.Column(db.Integer, primary_key=True)
    entry_id = db.Column(db.Integer, db.ForeignKey('mood_entries.id'), nullable=False, index=True)
    activity = db.Column(db.String(100), nullable=False, index=True)

    entry = db.relationship('MoodEntry', backref=db.backref('activity_mentions', lazy='dynamic'))


class EntryPerson(db.Model):
    """Person or family-role mention extracted from an entry via LLM.

    One row per (entry, mention) — an entry with `мама` and `Оля` produces
    two rows. The `tone` captures how the mention was framed in context,
    decoupling it from the day's overall rating (a bad day can still
    have positive mentions of someone who cheered the user up).
    """
    __tablename__ = 'entry_people'

    id = db.Column(db.Integer, primary_key=True)
    entry_id = db.Column(db.Integer, db.ForeignKey('mood_entries.id'), nullable=False, index=True)
    mention = db.Column(db.String(100), nullable=False, index=True)
    tone = db.Column(db.String(10), nullable=False)  # 'positive'|'neutral'|'negative'

    entry = db.relationship('MoodEntry', backref=db.backref('people_mentions', lazy='dynamic'))


class PeriodSummary(db.Model):
    """Layer 3: monthly/weekly emotional overviews"""
    __tablename__ = 'period_summaries'

    id = db.Column(db.Integer, primary_key=True)
    period_type = db.Column(db.String(10), nullable=False)  # 'month'
    period_key = db.Column(db.String(10), nullable=False, unique=True, index=True)  # '2025-01'
    summary = db.Column(db.Text)
    avg_rating = db.Column(db.Float)
    entry_count = db.Column(db.Integer)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class EntryEmbedding(db.Model):
    """Layer 2: vector embeddings for semantic search"""
    __tablename__ = 'entry_embeddings'

    id = db.Column(db.Integer, primary_key=True)
    entry_id = db.Column(db.Integer, db.ForeignKey('mood_entries.id'), unique=True, index=True)
    embedding = db.Column(db.LargeBinary)  # numpy float32 array as bytes
    text_hash = db.Column(db.String(32))   # MD5 of source text for change detection

    entry = db.relationship('MoodEntry', backref=db.backref('embedding_obj', uselist=False))


class UserPsychProfile(db.Model):
    """Layer 4: structured psychological profile (JSON)"""
    __tablename__ = 'user_psych_profile'

    id = db.Column(db.Integer, primary_key=True)
    profile_json = db.Column(db.Text, default='{}')
    version = db.Column(db.Integer, default=0)
    entries_analyzed = db.Column(db.Integer, default=0)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow)


class ChatMessage(db.Model):
    """Persistent chat history between sessions"""
    __tablename__ = 'chat_messages'

    id = db.Column(db.Integer, primary_key=True)
    role = db.Column(db.String(20), nullable=False)  # 'user' or 'assistant'
    content = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    # Sync fields
    uuid = db.Column(db.String(36), unique=True, index=True, default=_new_uuid)
    device_id = db.Column(db.String(36), nullable=True)


# ── Deep Mind: neural topic map ───────────────────────────────

class MindCluster(db.Model):
    """Topic cluster extracted from diary entry embeddings"""
    __tablename__ = 'mind_clusters'

    id = db.Column(db.Integer, primary_key=True)
    label = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text, nullable=True)
    emotional_weight = db.Column(db.Float, default=0.0)  # 0.0–1.0
    centroid = db.Column(db.LargeBinary, nullable=True)   # float32 384-dim
    entry_count = db.Column(db.Integer, default=0)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow)


class MindClusterEntry(db.Model):
    """Associates a MoodEntry with a MindCluster"""
    __tablename__ = 'mind_cluster_entries'

    id = db.Column(db.Integer, primary_key=True)
    cluster_id = db.Column(db.Integer, db.ForeignKey('mind_clusters.id'), index=True)
    entry_id = db.Column(db.Integer, db.ForeignKey('mood_entries.id'), index=True)

    cluster = db.relationship('MindCluster', backref=db.backref('member_entries', lazy='dynamic'))
    entry = db.relationship('MoodEntry', backref=db.backref('mind_cluster', uselist=False))


# ── Sync & Backup ────────────────────────────────────────────

class SyncMeta(db.Model):
    """Key-value store for sync metadata (device_id, last_sync, schema_version)"""
    __tablename__ = 'sync_meta'

    key = db.Column(db.String(50), primary_key=True)
    value = db.Column(db.Text)


class SyncConflict(db.Model):
    """Log of sync conflicts — kept for 30 days so the user can review"""
    __tablename__ = 'sync_conflicts'

    id = db.Column(db.Integer, primary_key=True)
    entry_date = db.Column(db.Date, nullable=False)
    local_note = db.Column(db.Text)
    local_rating = db.Column(db.Integer)
    remote_note = db.Column(db.Text)
    remote_rating = db.Column(db.Integer)
    remote_device = db.Column(db.String(36))
    winner = db.Column(db.String(10), default='remote')  # 'local' or 'remote'
    resolved_at = db.Column(db.DateTime, default=datetime.utcnow)


# ── Customization ───────────────────────────────────────────

class UserCustomization(db.Model):
    """Single-row table holding the user's UI preferences as a JSON blob.

    Owned by the customization module. Defined here so the model is
    available even when the module isn't loaded — only the module's
    context processor reads it. JSON storage keeps schema flexible:
    adding a new color/font option is a code change in the module, no
    further migrations needed.
    """
    __tablename__ = 'user_customization'

    id = db.Column(db.Integer, primary_key=True)
    settings_json = db.Column(db.Text, nullable=False, default='{}')
    updated_at = db.Column(db.DateTime, default=datetime.utcnow,
                           onupdate=datetime.utcnow)

"""
Database models for local diary application
Single-user version (no authentication needed)
"""
from datetime import datetime
from app import db


class MoodEntry(db.Model):
    """Daily mood entry with rating and notes"""
    __tablename__ = 'mood_entries'

    id = db.Column(db.Integer, primary_key=True)
    date = db.Column(db.Date, nullable=False, unique=True, index=True)
    rating = db.Column(db.Integer, nullable=False)  # 1-10 scale
    note = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

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
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

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

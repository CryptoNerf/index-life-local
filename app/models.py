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

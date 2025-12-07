"""
Script to import diary data from exported JSON file
Usage: python import_data.py diary_export.json [--user username]
"""
import json
import sys
import os
from datetime import datetime
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent))

from app import create_app, db
from app.models import MoodEntry, UserProfile


def import_data(json_file, specific_user=None):
    """Import data from JSON export file"""

    # Load JSON data
    try:
        with open(json_file, 'r', encoding='utf-8') as f:
            data = json.load(f)
    except FileNotFoundError:
        print(f"[Error] Error: File '{json_file}' not found")
        return False
    except json.JSONDecodeError as e:
        print(f"[Error] Error: Invalid JSON file - {e}")
        return False

    print(f"[File] Loading data from: {json_file}")
    print(f"[Date] Export date: {data.get('export_date', 'Unknown')}")
    print(f"[Users] Users in export: {len(data.get('users', []))}\n")

    # Filter for specific user if requested
    users_data = data.get('users', [])
    if specific_user:
        users_data = [u for u in users_data if u['username'] == specific_user]
        if not users_data:
            print(f"[Error] Error: User '{specific_user}' not found in export")
            return False
        print(f"[Target] Importing only user: {specific_user}\n")

    # Create Flask app context
    app = create_app()
    with app.app_context():

        # If importing single user, update profile
        if len(users_data) == 1:
            user_data = users_data[0]

            # Update or create profile
            profile = UserProfile.query.first()
            if profile:
                profile.username = user_data['username']
                profile.email = user_data.get('email', '')
            else:
                profile = UserProfile(
                    username=user_data['username'],
                    email=user_data.get('email', '')
                )
                db.session.add(profile)

            print(f"[User] Profile: {profile.username}")
            if user_data.get('email'):
                print(f"[Email] Email: {user_data['email']}")

        # Import mood entries
        total_imported = 0
        total_updated = 0
        total_skipped = 0

        for user_data in users_data:
            username = user_data['username']
            entries = user_data.get('mood_entries', [])

            print(f"\n[Importing] Importing {len(entries)} entries for {username}...")

            for entry_data in entries:
                try:
                    date_obj = datetime.fromisoformat(entry_data['date']).date()
                    rating = entry_data['rating']
                    note = entry_data.get('note', '')

                    # Check if entry already exists
                    existing_entry = MoodEntry.query.filter_by(date=date_obj).first()

                    if existing_entry:
                        # Update existing entry
                        existing_entry.rating = rating
                        existing_entry.note = note
                        existing_entry.updated_at = datetime.utcnow()
                        total_updated += 1
                    else:
                        # Create new entry
                        new_entry = MoodEntry(
                            date=date_obj,
                            rating=rating,
                            note=note
                        )
                        db.session.add(new_entry)
                        total_imported += 1

                except Exception as e:
                    print(f"  [Warning] Error importing entry for {entry_data.get('date')}: {e}")
                    total_skipped += 1

        # Commit all changes
        try:
            db.session.commit()
            print(f"\n{'='*60}")
            print(f"[Success] Import completed successfully!")
            print(f"{'='*60}")
            print(f"[Stats] Statistics:")
            print(f"   - New entries: {total_imported}")
            print(f"   - Updated entries: {total_updated}")
            print(f"   - Skipped/errors: {total_skipped}")
            print(f"   - Total in database: {MoodEntry.query.count()}")
            print(f"{'='*60}\n")
            return True

        except Exception as e:
            db.session.rollback()
            print(f"\n[Error] Error committing to database: {e}")
            return False


def main():
    """Main entry point"""
    if len(sys.argv) < 2:
        print("Usage: python import_data.py <json_file> [--user username]")
        print("\nExample:")
        print("  python import_data.py diary_export.json")
        print("  python import_data.py diary_export.json --user myusername")
        sys.exit(1)

    json_file = sys.argv[1]
    specific_user = None

    # Parse --user argument
    if len(sys.argv) >= 4 and sys.argv[2] == '--user':
        specific_user = sys.argv[3]

    success = import_data(json_file, specific_user)
    sys.exit(0 if success else 1)


if __name__ == '__main__':
    main()

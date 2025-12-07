"""
Convert Django dumpdata JSON to our export format
Usage: python convert_django_dump.py input.json output.json
"""
import json
import sys
from datetime import datetime
from pathlib import Path


def convert_django_dump(input_file, output_file):
    """Convert Django dumpdata format to our export format"""

    print(f"📁 Loading Django dump from: {input_file}")

    # Load Django dump
    try:
        with open(input_file, 'r', encoding='utf-8') as f:
            django_data = json.load(f)
    except FileNotFoundError:
        print(f"❌ Error: File '{input_file}' not found")
        return False
    except json.JSONDecodeError as e:
        print(f"❌ Error: Invalid JSON file - {e}")
        return False

    print(f"📊 Loaded {len(django_data)} objects from Django dump")

    # Organize data by model
    users = {}
    mood_entries = {}
    profiles = {}

    for obj in django_data:
        model = obj['model']
        pk = obj['pk']
        fields = obj['fields']

        if model == 'auth.user':
            users[pk] = {
                'username': fields.get('username'),
                'email': fields.get('email', ''),
                'date_joined': fields.get('date_joined'),
            }
        elif model == 'main.moodentry':
            user_id = fields.get('user')
            if user_id not in mood_entries:
                mood_entries[user_id] = []
            mood_entries[user_id].append({
                'date': fields.get('date'),
                'rating': fields.get('rating'),
                'note': fields.get('note', '')
            })
        elif model == 'main.profile':
            user_id = fields.get('user')
            profiles[user_id] = {
                'has_photo': bool(fields.get('photo')),
                'photo_path': fields.get('photo')
            }

    # Build export format
    export_data = {
        'export_date': datetime.now().isoformat(),
        'users': []
    }

    for user_id, user_data in users.items():
        user_export = {
            'username': user_data['username'],
            'email': user_data['email'],
            'date_joined': user_data['date_joined'],
            'profile': profiles.get(user_id, {'has_photo': False, 'photo_path': None}),
            'mood_entries': mood_entries.get(user_id, [])
        }
        export_data['users'].append(user_export)

        print(f"👤 User: {user_data['username']} - {len(user_export['mood_entries'])} entries")

    # Write output file
    try:
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(export_data, f, ensure_ascii=False, indent=2)

        print(f"\n{'='*60}")
        print(f"✅ Conversion completed successfully!")
        print(f"{'='*60}")
        print(f"Total users: {len(export_data['users'])}")
        print(f"Output file: {Path(output_file).absolute()}")
        print(f"{'='*60}\n")
        return True

    except Exception as e:
        print(f"\n❌ Error writing output file: {e}")
        return False


def main():
    """Main entry point"""
    if len(sys.argv) < 3:
        print("Usage: python convert_django_dump.py <input_file> <output_file>")
        print("\nExample:")
        print("  python convert_django_dump.py django_dump.json diary_export.json")
        sys.exit(1)

    input_file = sys.argv[1]
    output_file = sys.argv[2]

    success = convert_django_dump(input_file, output_file)
    sys.exit(0 if success else 1)


if __name__ == '__main__':
    main()

"""
Flask application factory
"""
from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from pathlib import Path

# Initialize extensions
db = SQLAlchemy()


def create_app(config_class='config.Config'):
    """Create and configure Flask application"""
    app = Flask(__name__)
    app.config.from_object(config_class)

    # Ensure upload folder exists
    upload_folder = Path(app.config['UPLOAD_FOLDER'])
    upload_folder.mkdir(parents=True, exist_ok=True)

    # Initialize extensions
    db.init_app(app)

    # Register blueprints/routes
    from app import routes
    app.register_blueprint(routes.bp)

    # Create database tables
    with app.app_context():
        db.create_all()

        # Migrate: add birthdate column if it doesn't exist (for existing DBs)
        from sqlalchemy import inspect, text
        inspector = inspect(db.engine)
        columns = [col['name'] for col in inspector.get_columns('user_profile')]
        if 'birthdate' not in columns:
            with db.engine.connect() as conn:
                conn.execute(text('ALTER TABLE user_profile ADD COLUMN birthdate DATE'))
                conn.commit()

        # Create default user profile if not exists
        from app.models import UserProfile
        if not UserProfile.query.first():
            default_profile = UserProfile(
                username='User',
                email=''
            )
            db.session.add(default_profile)
            db.session.commit()

    return app

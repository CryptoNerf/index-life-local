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

    # Register optional modules (voice, assistant)
    from app.modules import register_modules
    register_modules(app)

    # Warm up assistant module on startup (if enabled)
    if 'assistant' in app.config.get('ACTIVE_MODULES', []):
        try:
            from app.modules.assistant.background import warmup_async
            warmup_async(app)
        except Exception:
            pass

    # Context processor: makes module_active() available in all templates
    @app.context_processor
    def inject_modules():
        return {
            'module_active': lambda name: name in app.config.get('ACTIVE_MODULES', [])
        }

    # Create database tables (import all models so create_all sees them)
    with app.app_context():
        from app import models  # noqa: F401
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

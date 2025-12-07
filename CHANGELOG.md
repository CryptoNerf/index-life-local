# Changelog

All notable changes to this project will be documented in this file.

## [2.0.0-local] - 2025-12-07

### Added
- **Local-only architecture**: Complete migration from Django/VPS to Flask/SQLite
- **Privacy-first design**: All data stored locally, no cloud/server connections
- **Easy installation**: One-click install scripts for Windows/Linux/Mac
- **Automatic setup**: Virtual environment and dependency management
- **Data migration tools**: Scripts to import from Django version
- **Profile management**: User profile with name, email, and photo upload
- **Calendar view**: Heatmap-inspired design showing all mood entries
- **Daily entries**: Rate your day (1-10) with optional notes
- **Statistics**: Average mood rating and total entries count
- **Responsive design**: Mobile-friendly interface
- **Auto-browser launch**: Automatically opens browser on startup

### Changed
- **Architecture**: Migrated from Django to Flask for simplicity
- **Database**: Changed from PostgreSQL to SQLite for portability
- **User model**: Single-user system (removed multi-user authentication)
- **Deployment**: Changed from VPS deployment to local-only
- **Dependencies**: Reduced dependency footprint for faster installation

### Removed
- **Authentication system**: No login required (single user)
- **Server infrastructure**: No need for VPS, Nginx, Docker
- **PostgreSQL**: Replaced with lightweight SQLite
- **Cloud storage**: No remote data storage

## [1.0.0] - 2025-09-10

### Initial Django Version
- Multi-user Django application
- Deployed on VPS with Docker
- PostgreSQL database
- User authentication and profiles
- Mood calendar and entries
- Profile photo uploads

---

**Note**: Version 2.0.0 is a complete architectural change focusing on privacy and local-first approach.

# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**Lytter** is a Last.fm statistics web application built with FastAPI. It fetches and displays listening history, now-playing information, and various music statistics from Last.fm API. The app uses SQLite for database management and stores scrobbles (listening history) with incremental updates.

## Essential Commands

This project uses [mise](https://mise.jdx.dev/) as a task runner. Use `mise tasks` to see all available tasks.

### Development
```bash
# Quick commands via mise (recommended)
mise run r              # Run the development server (alias for 'run')
mise run i              # Install/update all dependencies (alias: 'install')

# Or use uv directly
uv run lytter           # Run the web application
uv run lytter-update    # Update scrobbles database
uv run lytter-status    # Check database status
```

### Code Quality
```bash
# Run type checking
uv run mypy src/

# Lint and format with ruff
uv run ruff check src/
uv run ruff format src/

# Run all pre-commit hooks
uv run pre-commit run --all-files
```

### Docker

**Quick commands via mise (recommended):**
```bash
mise run db             # Build image
mise run dt             # Tag for registry
mise run dp             # Push to registry
mise run dbp            # Build, tag, and push (all-in-one)
mise run du             # Start container
mise run dd             # Stop container
mise run dl             # Follow logs
```

**Or use docker/compose directly:**
```bash
# Local testing
docker compose up --build          # Build and run
docker compose up -d               # Start in detached mode
docker compose logs -f app         # Follow logs

# Build for registry
docker build -f Dockerfile.fastapi -t ghcr.io/engeir/lytter:latest .
docker push ghcr.io/engeir/lytter:latest
```

**Deploy to VPS:**
```bash
# On your VPS
docker pull ghcr.io/engeir/lytter:latest

# Run with environment variables
docker run -d \
  --name lytter \
  --restart unless-stopped \
  -p 8000:8000 \
  -v ./music.db:/app/music.db \
  --env-file .env \
  ghcr.io/engeir/lytter:latest

# Set up cron for updates
crontab -e
# Add: */15 * * * * docker exec lytter uv run lytter-cron >> ~/lytter-cron.log 2>&1
```

## Architecture

- **Framework**: FastAPI with Jinja2 templates
- **Database**: SQLite (music.db) - simple, file-based
- **APIs**: Last.fm API (via pylast), Genius API (lyrics)
- **Structure**: Modern src/ layout with proper packaging

### Project Structure
```
src/lytter/
  __init__.py           - Package initialization
  app.py                - Main FastAPI application
  update_db.py          - Manual database update script
  cron_updater.py       - Cron-friendly updater
  background_updater.py - Continuous background updater
  db_status.py          - Database status checker
  gap_checker.py        - Find gaps in scrobble history
  templates/            - Jinja2 HTML templates
  static/               - Static assets
```

### Key Components

**Main Application** (`src/lytter/app.py`):
- FastAPI app with routes for displaying stats
- `GetScrobbles` class: Fetches scrobbles from Last.fm API
- `CurrentStats` class: Generates Plotly visualizations
- Database helper functions: `get_db_connection()`, `init_db()`

**Update Scripts**:
- `update_db.py`: Interactive CLI with `--full`, `--thorough`, `--pages` options
- `cron_updater.py`: Silent, cron-friendly incremental updates
- `background_updater.py`: APScheduler-based continuous updater

**Database**:
- SQLite database at `music.db`
- Schema: `musiclibrary` table (artist, album, track, timestamps, MusicBrainz IDs)
- Incremental updates: Stops when encountering 50 consecutive existing scrobbles

### External APIs

1. **Last.fm API**: Via `pylast` library
   - Fetches scrobbles, now playing, artist/track/album stats
   - Requires `API_KEY`, `API_SECRET`, `USER_NAME`, `PASSWORD` from environment

2. **Genius API**: Via `lyricsgenius` library
   - Fetches song lyrics (optional)
   - Requires `GENIUS_TOKEN` from environment

## Environment Variables

Required in `.env` file (see `.env.example`):
```bash
API_KEY=your_lastfm_api_key
API_SECRET=your_lastfm_api_secret
USER_NAME=your_lastfm_username
PASSWORD=your_lastfm_password
GENIUS_TOKEN=your_genius_api_token  # optional
UPDATE_PASSWORD=password_for_db_updates
```

## Development Notes

### Code Style
- Docstrings follow NumPy convention (configured in pyproject.toml)
- Type hints encouraged but not strictly enforced
- Ruff handles linting with pydocstyle (D), pyflakes (F), pycodestyle (E), pylint (PL)

### Database Updates
The `GetScrobbles` class implements smart incremental updates:
- By default, stops fetching when it encounters 50 consecutive existing scrobbles
- Use `--full` parameter to force complete refresh
- Uses `CONSECUTIVE_SCROBBLES_THRESHOLD` constant for the stop threshold

### Running the Application
```bash
# Development (with auto-reload)
uv run uvicorn lytter.app:app --reload --host 0.0.0.0 --port 8000

# Production (via Docker)
docker run -p 8000:8000 --env-file .env ghcr.io/engeir/lytter:latest
```

### Deployment Pipeline
GitHub Actions (`.github/workflows/publish.yml`) builds and pushes to `ghcr.io/engeir/lytter` on pushes to the `release` branch.

# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

This is a Last.fm statistics web application built with Reflex (Python web framework). It fetches and displays listening history, now-playing information, and various music statistics from Last.fm API. The app uses SQLModel for database management and stores scrobbles (listening history) in a SQLite database.

## Essential Commands

This project uses [mise](https://mise.jdx.dev/) as a task runner. Use `mise tasks` to see all available tasks.

### Development
```bash
# Quick commands via mise (recommended)
mise run r              # Run the development server (alias for 'run')
mise run install        # Install/update all dependencies (alias: i)

# Or use uv directly
uv run reflex run       # Run the development server
uv run reflex init      # Initialize/reinitialize the app (after config changes)
uv run reflex export    # Export the app for production
```

### Database Management
```bash
# Create a new Alembic migration
uv run alembic revision --autogenerate -m "description"

# Apply migrations
uv run alembic upgrade head

# Rollback migration
uv run alembic downgrade -1
```

### Code Quality
```bash
# Run type checking
uv run mypy lastfm_stats

# Lint and format with ruff
uv run ruff check lastfm_stats
uv run ruff format lastfm_stats

# Run all pre-commit hooks
uv run pre-commit run --all-files
```

### Docker (Production-Ready Single-Container Setup)

The app uses a **production-ready single-container** approach:
- **Single image** with Redis, backend, and pre-built frontend
- **Easy deployment** - just push and pull one image
- **Fast startup** - frontend pre-built during image build (~5 sec startup)
- **Ready for VPS** - works with docker run or docker-compose

**Quick commands via mise (recommended):**
```bash
mise run db             # Build image (takes ~10 min first time)
mise run dub            # Build and start - alias for docker:up-build
mise run du             # Start container - alias for docker:up
mise run dd             # Stop container - alias for docker:down
mise run dl             # Follow logs - alias for docker:logs
mise run dp             # Push to registry - alias for docker:push

# Other tasks
mise run docker:build-direct    # Build with proper tag for pushing
mise run docker:build-clean     # Clean build without cache
mise run docker:restart         # Restart container
```

**Or use docker/compose directly:**
```bash
# Local testing
docker compose up --build          # Build and run
docker compose up -d               # Start in detached mode
docker compose logs -f app         # Follow logs

# Build for registry
docker build -t ghcr.io/engeir/lastfm-stats:latest .
docker push ghcr.io/engeir/lastfm-stats:latest
```

**Build Performance:**
- **First build**: ~10 minutes (downloads npm packages, builds frontend)
- **Code-only changes**: ~5-10 seconds (cached layers)
- **Container startup**: ~5 seconds (everything pre-built)
- **Image size**: ~1GB (optimized with slim base image)

**Deploy to VPS:**
```bash
# On your VPS
docker pull ghcr.io/engeir/lastfm-stats:latest

# Run with environment variables
docker run -d \
  --name lastfm-stats \
  --restart unless-stopped \
  -p 80:3000 \
  -p 8000:8000 \
  -v /path/to/reflex.db:/app/reflex.db \
  -e API_KEY=your_key \
  -e API_SECRET=your_secret \
  -e USER_NAME=your_username \
  -e PASSWORD=your_password \
  -e GENIUS_TOKEN=your_token \
  -e UPDATE_PASSWORD=your_update_password \
  ghcr.io/engeir/lastfm-stats:latest

# Or use with .env file
docker run -d \
  --name lastfm-stats \
  --restart unless-stopped \
  -p 80:3000 \
  -p 8000:8000 \
  -v /path/to/reflex.db:/app/reflex.db \
  --env-file /path/to/.env \
  ghcr.io/engeir/lastfm-stats:latest
```

**Architecture:**
- Single container with everything built-in (Redis + backend + frontend)
- Frontend pre-built with `reflex export` during image build
- Backend runs in production mode (`--env prod`)
- Redis runs in container for state management
- Database mounted as volume (persists across restarts)

**Workflow:**
1. Develop locally: `uv run reflex run`
2. Build image: `mise run docker:build-direct`
3. Test locally: `docker run --env-file .env -p 3000:3000 -p 8000:8000 ghcr.io/engeir/lastfm-stats:latest`
4. Push to registry: `mise run dp`
5. Deploy to VPS: `docker pull && docker run`

See `docker-build-guide.md` for detailed information.

## Architecture

### Application Structure

- **`lastfm_stats/lastfm_stats.py`**: Main app entry point. Configures the Reflex app with theme settings (purple accent, inherit appearance).
- **`rxconfig.py`**: Reflex configuration including database URL, app name, and plugins (sitemap).
- **`lastfm_stats/config.py`**: Global configuration that loads environment variables for Last.fm API credentials, Genius API token, and timezone settings.

### Key Components

**Pages** (`lastfm_stats/pages/`):
- `index.py`: Landing page with database update functionality (password-protected)
- `now_playing.py`: Core feature showing current track with detailed stats, lyrics, and visualizations
- Other pages in the directory provide additional views

**Data Layer** (`lastfm_stats/tools/`):
- `download_scrobbles.py`: Fetches scrobbles from Last.fm API and stores in SQLite via the `MusicLibrary` model. Implements incremental updates (stops when existing timestamp found) and full refresh mode.
- `mylast.py`: Creates the Last.fm network connection and provides utility functions for track/artist parsing
- `stats_lookup.py`: Generates statistics and visualizations using the stored scrobble data
- `get_lyrics.py`: Fetches lyrics from Genius API

**Database**:
- Uses SQLModel (Reflex's `rx.Model`) for ORM
- Primary model: `MusicLibrary` (in `download_scrobbles.py`) stores artist, album, track info with MusicBrainz IDs and unique timestamps
- SQLite database at `music.db`
- Alembic for migrations (config in `alembic.ini`, migrations in `alembic/versions/`)

### State Management

Reflex uses reactive state classes (subclass `rx.State`). Key states:
- `NowPlayingState` (in `now_playing.py`): Manages current track data, artist stats, lyrics, and Plotly figures
- `HiddenState` (in `index.py`): Handles password verification for database updates
- State methods use generators with `yield` for async-like operations or can use `@rx.event(background=True)` for true background tasks

### External APIs

1. **Last.fm API**: Via `pylast` library
   - Fetches scrobbles, now playing, artist/track/album stats
   - Requires `API_KEY`, `API_SECRET`, `USER_NAME`, `PASSWORD_HASH` from environment

2. **Genius API**: Via `lyricsgenius` library
   - Fetches song lyrics
   - Requires `GENIUS_TOKEN` from environment

## Environment Variables

Required in `.env` file (see `.env.example`):
- `API_KEY`: Last.fm API key
- `API_SECRET`: Last.fm API secret
- `USER_NAME`: Last.fm username
- `PASSWORD`: Last.fm password (hashed with `pylast.md5()`)
- `GENIUS_TOKEN`: Genius API access token
- `UPDATE_PASSWORD`: Password for triggering database updates via web UI

## Development Notes

### Code Style
- Docstrings follow NumPy convention (configured in pyproject.toml)
- Type hints are enforced (mypy configured for strict checking)
- Ruff handles linting with pydocstyle (D), pyflakes (F), pycodestyle (E), pylint (PL), and more

### Database Updates
The `GetScrobbles` class in `download_scrobbles.py` implements smart incremental updates:
- By default, stops fetching when it encounters an existing timestamp
- Use `full=True` parameter to force complete refresh (useful after data corruption)
- Rate limiting via `pause_duration` (currently 0.2s, but commented out)

### Reflex-Specific Patterns
- Components are functions that return `rx.Component`
- Use `@template` decorator (from `templates/template.py`) for consistent page layout
- State updates trigger automatic UI re-renders
- Conditional rendering via `rx.cond(condition, true_case, false_case)`

### Timezone Handling
Default timezone is Europe/Oslo (`pendulum.timezone("Europe/Oslo")`). Timestamps from Last.fm API are converted to this timezone for display.

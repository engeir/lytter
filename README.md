# lytter

Last.fm statistics dashboard built with FastAPI. Tracks scrobbles, displays listening
history, and generates music stats with Plotly visualizations.

## Configuration

Create `.env` with:

```bash
API_KEY=your_lastfm_api_key
API_SECRET=your_lastfm_api_secret
USER_NAME=your_lastfm_username
PASSWORD=your_lastfm_password
GENIUS_TOKEN=your_genius_api_token  # optional, for lyrics
```

## Install

### Run with Docker

**First time setup:**

```bash
# Create database file with correct permissions (important!)
touch music.db
sudo chown 1000:1000 music.db
```

Then run the container:

```bash
# Pull and run latest
docker pull ghcr.io/engeir/lytter:latest
docker run -d \
  --name lytter \
  --restart unless-stopped \
  -p 8000:8000 \
  -v ./music.db:/app/music.db \
  --env-file .env \
  ghcr.io/engeir/lytter:latest

# Or specific version
docker pull ghcr.io/engeir/lytter:2025.11.13
```

Or use docker compose:

```bash
mise run du   # or: docker compose up -d
```

### Database Updates

Set up a cron job to update scrobbles automatically:

```bash
# Add to crontab (every 15 minutes)
*/15 * * * * docker exec lytter uv run lytter-cron >> ~/lytter-cron.log 2>&1
```

Manual update:

```bash
docker exec lytter uv run lytter-update
```

## Local Development

### Quick Start

```bash
# Install dependencies
mise run i  # or: uv sync
# Set up environment variables
fnox export -f env -o .env
# Run dev server
mise run r  # or: uv run lytter
# Access at http://localhost:8000

# Code quality
hk fix
```

### Build & Push to Registry

Deploying new versions with

```bash
# Build, tag, and push (all-in-one)
mise run dbp

# Or step by step:
mise run db   # Build: docker compose build
mise run dt   # Tag for registry
mise run dp   # Push to registry
```

> To push to the GitHub container registry, create a PAT with read, write, delete
> package rights, then export the token and login, as described
> [here](https://docs.github.com/en/packages/working-with-a-github-packages-registry/working-with-the-container-registry#authenticating-with-a-personal-access-token-classic).

### Database Updates

The app fetches scrobbles incrementally (only new ones since last update).

```bash
# Manual update
uv run lytter-update
# Background updater (runs continuously)
uv run lytter-background
# Cron updater
uv run lytter-cron
# Check status
uv run lytter-status
# Check for gaps
uv run lytter-gaps
```

**Or as modules:**

```bash
uv run python -m lytter.update_db
uv run python -m lytter.cron_updater
```

## Architecture

- **Framework**: FastAPI with Jinja2 templates + HTMX
- **Database**: SQLite (music.db)
- **APIs**: Last.fm API (via pylast), Genius API (lyrics)
- **Visualizations**: Plotly charts
- **Styling**: Centralized CSS with variables (GitHub Dark theme)
- **Deployment**: Single Docker container
- **Structure**: Modern src/ layout with reusable macros

### Features

- **Dashboard**: Now playing, listening timeline, recent favorites, top artists
- **Artist Pages**: Listening history charts, top songs/albums
- **Album/Song Pages**: Detailed stats with breadcrumb navigation
- **Yearly Stats**: Time patterns (24h/weekly), top 20 lists, monthly ranking evolution
- **Search**: Fuzzy artist search with Unicode normalization
- **HTMX**: Server-side rendering for dynamic content (minimal JavaScript)

## References

- [Last.fm API analysis](https://geoffboeing.com/2016/05/analyzing-lastfm-history/)
- [Icons: Lucide](https://lucide.dev/)
- [Mise task runner](https://mise.jdx.dev/)

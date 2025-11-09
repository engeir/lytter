# lytter

Last.fm statistics dashboard built with FastAPI. Tracks scrobbles, displays listening
history, and generates music stats with Plotly visualizations.

## Quick Start

### Local Development

```bash
# Install dependencies
mise run i  # or: uv sync

# Run dev server
mise run r  # or: uv run lytter

# Access at http://localhost:8000

# Code quality
ruff check src/
uv run mypy src/
uv run pre-commit run --all-files
```

### Production (Docker)

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
docker pull ghcr.io/engeir/lytter:2025.11.7
```

Or use docker compose:

```bash
mise run du   # or: docker compose up -d
```

### Build & Deploy

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

## Configuration

Create `.env` with:

```bash
API_KEY=your_lastfm_api_key
API_SECRET=your_lastfm_api_secret
USER_NAME=your_lastfm_username
PASSWORD=your_lastfm_password
GENIUS_TOKEN=your_genius_api_token  # optional, for lyrics
UPDATE_PASSWORD=password_for_db_updates
```

## Architecture

- **Framework**: FastAPI with Jinja2 templates
- **Database**: SQLite (music.db)
- **APIs**: Last.fm API (via pylast), Genius API (lyrics)
- **Visualizations**: Plotly charts
- **Deployment**: Single Docker container
- **Structure**: Modern src/ layout

### Project Structure

```
src/lytter/
  app.py              - Main FastAPI application
  update_db.py        - Manual database update script
  cron_updater.py     - Cron job for scheduled updates
  background_updater.py - Background scrobble updates
  db_status.py        - Check database status
  gap_checker.py      - Find gaps in scrobble history
  templates/          - Jinja2 HTML templates
  static/             - Static assets
```

### Database Updates

The app fetches scrobbles incrementally (only new ones since last update).

**Using installed scripts:**

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

**Cron job (on your server):**

```bash
# Add to crontab
*/15 * * * * docker exec lytter uv run lytter-cron >> ~/lytter-cron.log 2>&1
```

## Deployment

The Docker image includes everything needed. Just pull and run on your VPS.

**Workflow:**

1. Build, tag & push: `mise run dbp`
2. On VPS: `docker pull ghcr.io/engeir/lytter:latest && docker run ...`

**Updates:** Repeat steps 1-2.

## References

- [Last.fm API analysis](https://geoffboeing.com/2016/05/analyzing-lastfm-history/)
- [Icons: Lucide](https://lucide.dev/)
- [Mise task runner](https://mise.jdx.dev/)

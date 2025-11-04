# Last.fm Stats - FastAPI Version

A simplified Last.fm statistics web application built with FastAPI. This version replaces the complex Reflex setup with a much simpler and more deployable FastAPI + SQLite + HTML templates approach.

## Features

- 📊 **Dashboard**: Overview of your listening statistics
- 🎵 **Now Playing**: Shows your currently playing track
- 👤 **Artist Stats**: Detailed statistics for any artist in your library
- 📈 **Charts**: Interactive visualizations using Plotly
- 🔄 **Database Updates**: Web interface to update your scrobbles
- 🐳 **Easy Deployment**: Simple Docker setup

## Quick Start

This project uses [uv](https://docs.astral.sh/uv/) for fast Python dependency management.

### 1. Install Dependencies

```bash
uv sync
```

### 2. Setup Environment

Copy `.env.example` to `.env` and fill in your Last.fm API credentials:

```bash
cp .env.example .env
```

Edit `.env`:
```
API_KEY=your_lastfm_api_key
API_SECRET=your_lastfm_api_secret
USER_NAME=your_lastfm_username
PASSWORD=your_lastfm_password
UPDATE_PASSWORD=your_admin_password
GENIUS_TOKEN=your_genius_token  # Optional for lyrics
```

### 3. Initialize/Update Database

Check your database status:
```bash
uv run python db_status.py
```

For first-time setup or if database is empty:
```bash
uv run python update_db.py --full
```

For regular incremental updates (recommended):
```bash
uv run python update_db.py
```

### 4. Run the Application

```bash
uv run python simple_app.py
```

The application will be available at http://localhost:8000

## Docker Deployment

### Build and Run with Docker Compose

```bash
docker-compose -f docker-compose.fastapi.yml up --build
```

### Build Docker Image

```bash
docker build -f Dockerfile.fastapi -t lastfm-stats-fastapi .
```

### Run Docker Container

```bash
docker run -d \
  --name lastfm-stats \
  -p 8000:8000 \
  -v $(pwd)/music.db:/app/music.db \
  --env-file .env \
  lastfm-stats-fastapi
```

## VPS Deployment

1. **Copy files to your server**:
   ```bash
   scp -r * user@your-server:/path/to/app/
   ```

2. **Install Docker on your VPS** (if not already installed):
   ```bash
   curl -fsSL https://get.docker.com -o get-docker.sh
   sudo sh get-docker.sh
   ```

3. **Build and run**:
   ```bash
   cd /path/to/app
   docker-compose -f docker-compose.fastapi.yml up -d --build
   ```

4. **Setup reverse proxy** (optional, with nginx):
   ```nginx
   server {
       listen 80;
       server_name your-domain.com;

       location / {
           proxy_pass http://localhost:8000;
           proxy_set_header Host $host;
           proxy_set_header X-Real-IP $remote_addr;
       }
   }
   ```

## API Endpoints

- `GET /` - Main dashboard
- `GET /artist/{artist_name}` - Artist statistics page
- `GET /admin` - Database management page
- `POST /update-database` - Update scrobbles (requires password)
- `GET /top-artists` - JSON API for top artists
- `GET /charts/listening-timeline` - JSON API for timeline chart
- `GET /charts/top-artists-bar` - JSON API for top artists chart

## Database

The application uses SQLite with a simple schema:

```sql
CREATE TABLE musiclibrary (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    artist TEXT NOT NULL,
    artist_mbid TEXT,
    album TEXT,
    album_mbid TEXT,
    track TEXT NOT NULL,
    track_mbid TEXT,
    timestamp INTEGER UNIQUE NOT NULL
);
```

### Database Updates (No Web Interface)

**Important**: This version removes the web-based admin panel. Database updates are handled via command-line tools and automated background processes for security and reliability.

The system supports two types of updates:

**🔄 Incremental Updates (Recommended)**
```bash
uv run python update_db.py
```
- Only fetches new scrobbles since the last update
- Fast and efficient for regular use
- Automatically stops when it finds 50 consecutive old scrobbles
- Limits to first 5 pages of Last.fm API for speed
- Uses smart timestamp checking instead of error-prone IntegrityError handling

**⚠️ Full Updates (Use with Caution)**
```bash
uv run python update_db.py --full
```
- Downloads your entire Last.fm history
- Only use for first-time setup or if database is corrupted
- Can take a long time for users with large histories

**📊 Database Status**
```bash
uv run python db_status.py
```
- Shows total scrobbles, artists, tracks
- Displays latest and oldest scrobbles
- Indicates if database needs updating
- Shows listening statistics

### Automated Background Updates

For production deployment, set up automatic updates using cron:

**Setup Cron Job:**
```bash
# Edit crontab
crontab -e

# Add this line for hourly updates at 5 minutes past each hour:
5 * * * * cd /path/to/lastfm-stats && /usr/bin/uv run python cron_updater.py >> /var/log/lastfm-cron.log 2>&1
```

**Alternative Schedules:**
```bash
# Every 4 hours
5 */4 * * * cd /path/to/lastfm-stats && /usr/bin/uv run python cron_updater.py

# Twice daily (6 AM and 6 PM)
0 6,18 * * * cd /path/to/lastfm-stats && /usr/bin/uv run python cron_updater.py
```

**Background Service (Optional):**
```bash
# Run continuous background updater (updates every hour)
uv run python background_updater.py
```

### Robust Incremental Logic

The new implementation fixes previous issues:

1. **Timestamp Pre-checking**: Gets latest timestamp from database first
2. **Smart Stopping**: Stops after 50 consecutive old scrobbles (not just first duplicate)
3. **Explicit Existence Check**: Uses SELECT query instead of relying on IntegrityError
4. **Limited Page Fetching**: Only checks first 5 pages for incremental updates
5. **Better Error Handling**: Proper timeouts and error recovery
6. **Logging**: All updates are logged for monitoring

### Update Strategy

**The Problem with Pure Incremental Updates:**
Incremental updates assume that if the latest scrobble in your DB matches the latest from Last.fm, everything in between is also present. However, network errors, API rate limits, or process interruptions during previous updates can create gaps.

**Recommended Multi-Layer Approach:**

**Layer 1: Quick Daily Updates (Cron)**
```bash
# Fast incremental for recent scrobbles
5 * * * * cd /path/to/lastfm-stats && uv run python cron_updater.py
```

**Layer 2: Thorough Weekly Updates**
```bash
# More thorough incremental update (checks more pages)
0 2 * * 0 cd /path/to/lastfm-stats && uv run python update_db.py --thorough
```

**Layer 3: Gap Detection (Weekly)**
```bash
# Check for and fill any gaps in the last week
0 3 * * 0 cd /path/to/lastfm-stats && uv run python gap_checker.py --hours 168 --fix
```

**Manual Commands:**
```bash
# Check for gaps without fixing
uv run python gap_checker.py --hours 48

# Fix any found gaps
uv run python gap_checker.py --hours 168 --fix

# Thorough incremental update
uv run python update_db.py --thorough

# Nuclear option: full update (rare)
uv run python update_db.py --full
```

**Monitoring:**
```bash
# Check database status
uv run python db_status.py

# Monitor update logs
tail -f lastfm_updates.log
```

This layered approach provides:
- **Fast daily updates** for normal operation
- **Thorough weekly verification** to catch any missed scrobbles
- **Gap detection and filling** for bulletproof reliability
- **Full update option** for disaster recovery

You'll never lose scrobbles and the system mostly runs fast incremental updates.

## Key Differences from Reflex Version

1. **Simpler Stack**: FastAPI + SQLite + Jinja2 templates instead of Reflex
2. **Better Performance**: Faster startup and lower memory usage
3. **Easier Deployment**: Standard Python app that works everywhere
4. **No Complex Dependencies**: Fewer moving parts, easier to debug
5. **Standard Patterns**: Uses well-known web development patterns
6. **Modern Tooling**: Uses uv for fast dependency management

## Migrating from Reflex

If you have an existing `music.db` from the Reflex version, it should work directly with this FastAPI version since we use the same database schema.

## Development

### Local Development

```bash
# Install dependencies
uv sync

# Run with auto-reload
uv run uvicorn simple_app:app --reload --host 0.0.0.0 --port 8000
```

### Adding New Features

The application structure is straightforward:

- `simple_app.py` - Main FastAPI application
- `templates/` - Jinja2 HTML templates
- `static/` - Static files (CSS, JS, images)
- `pyproject.toml` - Project configuration and dependencies
- `uv.lock` - Locked dependency versions

## Troubleshooting

### Database Issues

If you encounter database issues, you can reset it:

```bash
rm music.db
python -c "from simple_app import init_db; init_db()"
```

### Import Errors

Make sure all dependencies are installed:

```bash
uv sync
```

### Port Already in Use

Change the port in the Docker Compose file or when running locally:

```bash
uv run uvicorn simple_app:app --port 8001
```

## Why FastAPI Instead of Reflex?

1. **Maturity**: FastAPI is battle-tested and widely used
2. **Documentation**: Excellent documentation and community support
3. **Performance**: Much faster than Reflex
4. **Deployment**: Works on any Python hosting platform
5. **Debugging**: Standard Python debugging tools work perfectly
6. **Flexibility**: Easy to extend and customize
7. **Resources**: Lower memory and CPU usage

This FastAPI version gives you the same functionality as the Reflex version but with much better reliability and ease of deployment.

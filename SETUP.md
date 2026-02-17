# Focus — Setup Guide

## What's Installed

| Component | Status | Details |
|-----------|--------|---------|
| Python | 3.14.2 | System install (Arch) |
| Virtual env | `.venv/` | All deps installed here |
| PostgreSQL | Running | `focus` database with 15 tables |
| Ollama | Running | `qwen3:4b` pulled (local classification) |
| Google OAuth | Ready | `~/.config/focus/google-credentials.json` |
| Config | Written | `~/.config/focus/config.toml` |
| Vault dir | Created | `~/Focus-Vault/` |
| Chroma dir | Created | `~/.local/share/focus/chroma/` |
| Anthropic API key | Loaded | `~/focus/.env` (auto-loaded by `python-dotenv`) |

## Activate the Environment

Every time you open a new terminal:

```bash
source ~/focus/.venv/bin/activate
```

Or add this to your `~/.bashrc` for automatic activation:

```bash
echo 'alias focus="~/focus/.venv/bin/focus"' >> ~/.bashrc
source ~/.bashrc
```

## Anthropic API Key

Already configured in `~/focus/.env` and auto-loaded on startup via `python-dotenv`.
The `.env` file is gitignored so it will never be committed.

To change or rotate the key, edit `~/focus/.env`:

```
ANTHROPIC_API_KEY=sk-ant-...
```

## Add Your First Email Account

```bash
focus account add
```

This opens a browser for Google OAuth. You need:
- A Google Cloud project with Gmail API and Drive API enabled
- An OAuth 2.0 Client ID (Desktop type)
- The client credentials file at `~/.config/focus/google-credentials.json`

## Daily Workflow

```bash
# Pull new emails + Drive docs, classify, extract, resolve entities
focus sync

# Generate your Obsidian vault
focus generate

# Open ~/Focus-Vault/ in Obsidian
```

## All Commands

```
focus init          First-time setup wizard
focus status        Show data counts and sync state
focus sync          Sync emails + Drive, process new data
focus generate      Regenerate Obsidian vault + CLAUDE.md
focus search TEXT   Search across all data (text-based)
focus search TEXT -s  Semantic search (needs: pip install chromadb)
focus reindex       Rebuild semantic search index
focus capture       Capture decisions from Claude Code sessions
focus daemon        Run continuously (sync every 15min)
focus reprocess     Re-extract raw data with current models

focus account add/list/auth/enable/disable/priority
focus project list/pin/unpin/priority/deadline/archive
focus task list/create/status/priority/assign
focus sprint create/list/deactivate
focus priorities    View ranked project priorities
```

## REST API

```bash
uvicorn src.api.routes:app --reload --host 0.0.0.0 --port 8000
```

Then open http://localhost:8000/docs for interactive Swagger UI.

Key endpoints:
- `GET /health` — Health check
- `GET /projects` — List projects (filter: `?status=active&tier=complex`)
- `GET /tasks` — List tasks (filter: `?project_slug=...&status=backlog`)
- `GET /people` — List known people
- `GET /emails` — List emails (filter: `?classification=human&needs_reply=true`)
- `GET /documents` — List Drive docs (filter: `?folder=Projects`)
- `GET /priorities` — Ranked priorities (filter: `?scope=today`)
- `GET /search?q=...` — Semantic search
- `POST /sync` — Trigger sync
- `POST /generate` — Regenerate vault
- `POST /capture` — Capture Claude Code sessions

## Optional: Semantic Search

```bash
pip install chromadb
focus reindex     # Build vector index from existing data
focus search "what did I promise about the API" --semantic
```

## Optional: Daemon Mode

Run Focus as a background service that syncs and regenerates automatically:

```bash
focus daemon --interval 15
```

Or create a systemd user service:

```bash
mkdir -p ~/.config/systemd/user
cat > ~/.config/systemd/user/focus.service << 'EOF'
[Unit]
Description=Focus Daemon
After=network.target postgresql.service

[Service]
Type=simple
ExecStart=%h/focus/.venv/bin/focus daemon --interval 15
Restart=on-failure
RestartSec=30
EnvironmentFile=%h/focus/.env

[Install]
WantedBy=default.target
EOF

systemctl --user daemon-reload
systemctl --user enable --now focus
```

## File Layout

```
~/focus/
  .venv/                  Python virtual environment
  src/
    cli/                  CLI commands (Typer)
    ingestion/            Gmail, Drive, Claude Code capture
    processing/           Classification, extraction, entity resolution
    storage/              DB models, vectors, raw archive
    output/               Vault, kanban, daily notes, CLAUDE.md
    api/                  FastAPI REST endpoints
    config.py             Settings (reads ~/.config/focus/config.toml)
    daemon.py             Background sync loop
    priority.py           Priority scoring engine
  tests/                  249 tests
  schema.sql              Database DDL
  docs/FEATURES.md        Feature registry (18/19 done)

~/.config/focus/
  config.toml             Main config
  google-credentials.json OAuth client credentials

~/Focus-Vault/            Generated Obsidian vault (open in Obsidian)
```

## Testing

```bash
source ~/focus/.venv/bin/activate
pytest tests/ -v        # 249 tests, all passing
```

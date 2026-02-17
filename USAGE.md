# Focus — Usage Guide

## Quick Start

```bash
# Activate the environment
source ~/focus/.venv/bin/activate

# Check everything is working
focus status
```

That's it. Everything else (DB, API key, Ollama, config) is already set up.

---

## First Run: Connect Gmail

```bash
focus account add
```

Follow the browser OAuth prompt. Once connected:

```bash
# Pull emails + Drive docs, classify them, extract tasks/people/commitments
focus sync

# Generate your Obsidian vault
focus generate
```

Open `~/Focus-Vault/` in Obsidian. You'll see your inbox, projects, people, and tasks organized automatically.

---

## Day-to-Day Commands

### Sync & Generate

```bash
focus sync                  # Fetch new emails + Drive docs, process everything
focus generate              # Rebuild the vault from current DB state
```

Or just run the daemon and forget about it:

```bash
focus daemon                # Syncs every 15 min, regenerates vault automatically
focus daemon -i 5           # Sync every 5 min instead
```

### Search

```bash
focus search "project name"           # Text search across emails, docs, people, projects, tasks
focus search "deadline promise" -s     # Semantic search (AI-powered, searches by meaning)
```

### View Status

```bash
focus status                # Data counts, classification breakdown, sync state
focus priorities            # Projects ranked by effective priority
```

### Manage Projects

```bash
focus project list                          # All projects
focus project pin my-project                # Pin to top of priority list
focus project priority my-project critical  # Set priority: critical/high/normal/low
focus project deadline my-project 2026-03-01 "MVP launch"
focus project archive my-project            # Archive when done
```

### Manage Tasks

```bash
focus task list                             # All tasks
focus task list --project my-project        # Tasks for one project
focus task create "Build the auth system"   # Create a task
focus task status TASK_ID in_progress       # Move: backlog/in_progress/waiting/done
focus task priority TASK_ID high            # Set priority
focus task assign TASK_ID "Jane Doe"        # Assign to someone
```

### Sprints

```bash
focus sprint create "MVP Push" my-project 14    # 14-day sprint on a project
focus sprint list                               # Active sprints
focus sprint deactivate SPRINT_ID               # End early
```

Sprints boost a project's priority by 2x. When they expire, the project auto-archives.

### Capture Claude Code Decisions

```bash
focus capture                    # Scan all Claude Code sessions, extract decisions
focus capture -p my-project      # Just one project's sessions
focus capture --no-extract       # Archive sessions without AI extraction
```

### Reprocess Old Data

```bash
focus reprocess --dry-run         # See what would be reprocessed
focus reprocess --since 2026-01-01
```

### Manage Accounts

```bash
focus account list                            # Show all accounts
focus account priority work@gmail.com 2.0     # Weight work email higher
focus account disable personal@gmail.com      # Pause syncing
focus account enable personal@gmail.com       # Resume
```

---

## REST API

```bash
source ~/focus/.venv/bin/activate
uvicorn src.api.routes:app --reload
```

Open http://localhost:8000/docs for Swagger UI.

| Endpoint | Method | What |
|----------|--------|------|
| `/health` | GET | Health check |
| `/projects` | GET | List projects (`?status=active&tier=complex`) |
| `/projects/{slug}` | GET | Single project |
| `/tasks` | GET | List tasks (`?project_slug=...&status=backlog`) |
| `/people` | GET | List people |
| `/emails` | GET | List emails (`?classification=human&needs_reply=true`) |
| `/documents` | GET | List Drive docs (`?folder=Projects`) |
| `/priorities` | GET | Ranked priorities (`?scope=today`) |
| `/search` | GET | Semantic search (`?q=...&limit=10`) |
| `/sync` | POST | Trigger sync |
| `/generate` | POST | Regenerate vault |
| `/capture` | POST | Capture Claude Code sessions |

---

## How It Works

```
Gmail/Drive  -->  Classify (local Ollama)  -->  Extract (Claude Haiku)  -->  Resolve entities
                                                                                  |
Claude Code sessions  -->  Parse JSONL  -->  Extract decisions (Haiku)            |
                                                                                  v
                                                                            PostgreSQL
                                                                                  |
                                                      +----------+----------+----+----+
                                                      |          |          |         |
                                                   Vault    CLAUDE.md   Kanban   Daily Notes
                                                (Obsidian)
```

- **Emails** are classified locally (free, fast) then routed:
  - Human emails → deep extraction (tasks, commitments, people, projects)
  - Automated emails → regex parsing (orders, tracking, amounts)
  - Newsletters → archived
  - Spam → skipped
- **Drive docs** are synced incrementally, text extracted, content-hash deduped
- **Claude Code sessions** are scanned from `~/.claude/projects/`, decisions extracted
- **Everything** is stored permanently in `raw_interactions` for future reprocessing
- **Every AI call** is logged with tokens, cost, and latency

---

## Key Paths

| Path | What |
|------|------|
| `~/focus/.venv/bin/focus` | CLI binary |
| `~/focus/.env` | API key (gitignored) |
| `~/.config/focus/config.toml` | Main config |
| `~/.config/focus/google-credentials.json` | Google OAuth client |
| `~/Focus-Vault/` | Generated Obsidian vault |
| `~/.local/share/focus/chroma/` | Vector search index |

## Troubleshooting

```bash
# Check if PostgreSQL is running
systemctl status postgresql

# Check if Ollama is running
ollama list

# Verify API key is loaded
source ~/focus/.venv/bin/activate
python -c "from src.config import get_settings; s=get_settings(); print('OK' if s.anthropic.api_key else 'NO KEY')"

# Run tests
pytest tests/ -v
```

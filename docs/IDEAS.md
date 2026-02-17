# Future Ideas

## Ingestion Sources

### Zoom / Audio File Notetaker
Ingest Zoom recordings or raw audio files. Transcribe via Whisper (local or API), then run through the extraction pipeline to pull out tasks, commitments, decisions, and people mentioned. Could auto-link to calendar events for meeting context.

### Claude / ChatGPT History Import
Bootstrap Focus with existing AI conversation history. Both Claude and ChatGPT support conversation export. Parse these to extract:
- Projects discussed (seed the project graph)
- Decisions made (populate decision log)
- People mentioned (seed the people graph)
- Technical context and preferences

This solves the cold-start / onboarding problem — instead of waiting for emails to slowly build context, import months of AI conversations to immediately understand what the user cares about.

### Chat History as Onboarding
The onboarding problem: Focus needs data to be useful, but first-run has nothing. Beyond AI history, consider:
- Let user point at an existing Obsidian vault / notes directory
- Import browser bookmarks for project signals
- Import calendar for people + meeting patterns
- Quick interview mode: ask user 10 questions to seed projects, people, priorities

## Machine Monitoring (NEXT UP)

Full context capture across 2 machines (laptop + desktop), synced to one Focus DB.

### Architecture

```
Machine A (laptop)                    Machine B (desktop)
┌─────────────────────┐              ┌─────────────────────┐
│ ActivityWatch        │              │ ActivityWatch        │
│ Focus Daemon         │──────┐ ┌────│ Focus Daemon         │
│ Git Watcher          │      │ │    │ Git Watcher          │
│ Shell History        │      │ │    │ Shell History         │
│ Claude Code Sessions │      ▼ ▼    │ Claude Code Sessions │
└─────────────────────┘    PostgreSQL └─────────────────────┘
                           (on LAN)
```

Both machines run the Focus daemon + ActivityWatch. Both point at the same
postgres over LAN (or SSH tunnel). Content-hash dedup handles overlap.

### Data Sources (per machine)

1. **ActivityWatch** (open source, local-first)
   - Active window title + app name, polled every 5-10 seconds
   - Install: `pip install activitywatch` or system package
   - Focus ingests via AW's local REST API (localhost:5600)
   - Gives us: what app you're using, what document/page is open, time spent

2. **Git activity**
   - Scan configured repo directories for recent commits
   - Extract: repo, branch, commit messages, files changed, timestamps
   - Maps to projects automatically (repo name → project slug)
   - Runs on each `focus sync`

3. **Shell history**
   - Read ~/.bash_history or ~/.zsh_history (with timestamps if HISTTIMEFORMAT set)
   - Extract: commands run, working directories, timestamps
   - Useful for detecting what project you're actively coding on

4. **Claude Code sessions** (already built: src/ingestion/claude_code.py)
   - Captures decisions, code changes, conversation context
   - Already feeds into the project/decision graph

5. **File watcher** (optional, heavier)
   - inotify (Linux) / fsevents (macOS) on key directories
   - Track file saves in project directories
   - Maps file paths → projects

6. **Browser history** (optional)
   - Read Chrome/Firefox history SQLite DB
   - Extract: URLs visited, page titles, timestamps
   - Useful for research activity tracking

### Implementation Plan

Phase 1 — ActivityWatch integration:
- New file: `src/ingestion/activitywatch.py`
- Poll AW API on each sync for window events since last cursor
- Store as raw_interactions (source_type="activitywatch")
- Classify into project associations (window title → project matching)

Phase 2 — Git + shell history:
- New file: `src/ingestion/git_activity.py`
- Scan repos, extract commits, map to projects
- New file: `src/ingestion/shell_history.py`
- Parse history file, store with timestamps

Phase 3 — Multi-machine sync:
- Both machines point at same postgres (LAN IP or SSH tunnel)
- Each machine has its own `machine_id` in config
- All raw_interactions tagged with machine_id
- Dedup by content hash handles any overlap
- Vault generation happens on either machine (idempotent)

Phase 4 — Daily activity summary:
- New section in TODAY.md: "What I worked on"
- Aggregated from AW + git + shell across machines
- Auto-detect project context switches
- Show time breakdown by project

### DB Changes Needed

- Add `machine_id` column to raw_interactions table
- Add `source_type` values: "activitywatch", "git_commit", "shell_command"
- New table or use existing: activity_events (timestamp, machine_id, app, title, project_id, duration_seconds)

### iOS Integration

iOS won't let you run daemons or monitor windows. But you can still capture
what matters through three channels:

**1. iOS Shortcuts → Focus API (easiest, most useful)**
The Focus API already exists (`src/api/routes.py`). Expose it via Tailscale/WireGuard
on your LAN. Then build iOS Shortcuts that POST to it:
- "Log what I'm working on" — quick capture shortcut, sends text to `/api/capture`
- "Start focus session" — logs a work block start with project tag
- "End focus session" — logs end, calculates duration
- Auto-triggers: when you arrive at a location, connect to WiFi, open an app
- Siri: "Hey Siri, log that I'm working on Focus" → hits the API

**2. Apple Screen Time data**
- Screen Time tracks app usage per day (which apps, how long)
- No official API, but the data lives in a SQLite DB on macOS if you have
  iCloud sync enabled: `~/Library/Application Support/Knowledge/knowledgeC.db`
- Ingest this on the Mac side — gives you iOS app usage for free
- Maps app names → project context (e.g., Slack = communication, Xcode = coding)

**3. iCloud-synced data**
- **Safari history**: syncs to Mac, readable from SQLite
- **Reminders**: accessible via macOS EventKit or `reminders` CLI
- **Notes**: synced, readable from macOS
- **Calendar**: already accessible via Google Calendar API or macOS EventKit
- **iMessage**: already planned (F-015) — captures conversations

**4. Future: Focus iOS app (PWA or native)**
- Show TODAY.md as a mobile dashboard
- Quick capture: tap to log a thought, task, or work session
- Show who you need to reply to
- Push notifications for commitments due

The iOS Shortcuts approach is the fastest to ship — it uses the API we already
have and Apple's built-in automation. No App Store review needed.

### Config Changes

```toml
[monitoring]
activitywatch_url = "http://localhost:5600"
git_repos = ["~/code/*", "~/projects/*"]
shell_history = true
machine_id = "laptop"  # unique per machine
```

## Processing Improvements

### Skip Classification for Obvious Non-Human Emails
Newsletters, marketing, and automated emails are identifiable by sender patterns (noreply@, no-reply@, *@mail.*, unsubscribe links in body, List-Unsubscribe header). Pre-filter these with zero-cost regex/header checks BEFORE hitting the Haiku API. Only spend tokens on emails that might actually be human.

Candidate heuristics:
- Sender contains noreply/no-reply/mailer-daemon/notifications
- Has List-Unsubscribe header
- Has precedence: bulk/list header
- Sender domain is known marketing platform (mailchimp, sendgrid, constantcontact, etc.)
- Body contains "unsubscribe" near the bottom

### Full Prompt/Response Logging
Ensure every LLM interaction is fully recorded:
- User prompts that trigger processing
- Full request payloads sent to models
- Full response payloads received
- Token counts and costs
- Which email/document triggered the call

This is partially done (ai_conversations table) but should be verified end-to-end, especially for the classifier and extractor paths.

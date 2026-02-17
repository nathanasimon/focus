# Focus — Roadmap & Setup Checklist

> What's working, what's next, and what you need to configure.
> Last updated: 2026-02-05

---

## The Core Thesis

Focus has two kinds of input, and they are not equally valuable:

**Passive data** — emails, Drive docs, calendar, shipping notifications. These are things that happen *to* you. They're useful for context but they're mostly noise. The current system handles these well.

**Active direction** — what you tell AI systems to do. When you sit down with Claude Code and say "build this feature" or "restructure the auth system" or "I need to prioritize X over Y," that is a direct statement of intent. It's not something to extract signal from — it IS the signal.

Right now Focus captures Claude Code sessions (F-019) and extracts decisions. But that's one channel of a much bigger picture:

- **Claude Code sessions** — captured (decisions, architecture choices, code direction)
- **Claude.ai web conversations** — NOT captured (project planning, brainstorming, research)
- **ChatGPT conversations** — NOT captured (same: planning, exploration, decisions)
- **Other AI tools** — NOT captured (Cursor, Copilot chat, Gemini, etc.)

Every time you have a 30-minute conversation with an AI about how to approach a problem, that's 30 minutes of pure, unfiltered priority signal. Focus should treat this as the primary input, not a secondary one after email.

---

## What's Working Now

18/19 features shipped. The core loop is functional:

| Layer | Status | Signal quality |
|-------|--------|---------------|
| Claude Code capture | Working | **Highest** — direct intent, decisions, architecture |
| Gmail ingestion | Working | Medium — mix of human signal and noise |
| Google Drive | Working | Medium — documents show what you're working on |
| Classification | Working | Filters noise so human emails surface |
| Deep extraction | Working | Pulls tasks/commitments/people from human emails |
| Entity resolution | Working | Connects people + projects across sources |
| Obsidian vault | Working | Flat structure: TODAY.md, INBOX.md, Projects/ |
| CLAUDE.md | Working | Auto-generated briefing for every Claude Code session |
| Priority system | Working | User pins, sprints, deadline urgency |
| Semantic search | Working | Chroma vector store, CLI + API |
| REST API | Working | Full CRUD + sync/generate/capture triggers |
| Daemon | Working | Background loop every 15 min |
| Raw archive | Working | Every interaction + AI call logged permanently |

**Not built yet:** F-015 (iMessage ingestion — macOS only)

---

## Immediate Setup — Do This Now

### 1. Reset and re-run processing

The classification system was rewritten this session. Clear old results and reprocess:

```bash
source ~/focus/.venv/bin/activate
focus reset-processing
focus sync
```

This will reclassify all emails with the improved date-aware pipeline and pre-filtering.

### 2. Verify config

Check `~/.config/focus/config.toml` has these sections:

```toml
[general]
vault_path = "~/Focus-Vault"
db_url = "postgresql+asyncpg://localhost/focus"

[anthropic]
# API key loaded from ~/focus/.env — don't put it here

[ollama]
model = "qwen3:4b"
base_url = "http://localhost:11434"

[sync]
interval_minutes = 15
drive_enabled = true

[vault]
auto_regenerate = true

[raw_storage]
enabled = true
store_ai_conversations = true
```

### 3. Daemon as systemd service

If not already done:

```bash
systemctl --user enable --now focus
```

See SETUP.md for the service file.

---

## Phase 1 — AI Conversation Capture (Highest Priority)

**Goal:** Capture all user-AI interaction as a first-class data source — not just Claude Code sessions, but every AI conversation across every tool.

### Why this comes first

Emails tell you what other people want from you. AI conversations tell you what *you* want. They contain:
- **Decisions** — "let's use PostgreSQL not SQLite," "the API should return JSON"
- **Priorities** — what you chose to work on today, this week
- **Project direction** — architecture discussions, feature plans, trade-offs considered
- **Knowledge** — explanations you asked for, things you learned
- **People context** — "I need to talk to Sarah about the API," "John's team owns auth"

An email saying "hey can you review my PR" is low-signal. A 45-minute Claude conversation where you redesigned the entire auth system is the highest signal Focus will ever see.

### What to build

| Source | Format | Effort | Signal |
|--------|--------|--------|--------|
| Claude Code sessions | JSONL in `~/.claude/projects/` | **Already built** | Decisions, code changes, architecture |
| Claude.ai web export | JSON export from claude.ai/settings | Small | Planning, brainstorming, research, project thinking |
| ChatGPT export | JSON export from settings | Small | Same — planning, exploration, decisions |
| Cursor AI chat | Local SQLite or logs | Medium | Code-level decisions, similar to Claude Code |
| API conversation logs | Already in `ai_conversations` table | **Already built** | What Focus itself asked the LLM and why |

### Implementation plan

**Step 1: Claude.ai history import** — `src/ingestion/claude_web.py`
- Parse the JSON export (conversations → messages)
- Run each conversation through Haiku to extract: decisions, projects discussed, people mentioned, priorities stated, knowledge gained
- Store as raw_interactions (source_type="claude_web_conversation")
- This immediately seeds the project graph, decision log, and people graph with months of real context
- One-time import + periodic re-import as conversations accumulate

**Step 2: ChatGPT history import** — `src/ingestion/chatgpt.py`
- Same idea, different JSON format
- ChatGPT exports include all conversations with timestamps
- Extract the same fields: decisions, projects, people, priorities

**Step 3: Continuous Claude Code capture improvements**
- Already captures decisions. Enhance to also extract:
  - **Projects worked on** — map session → project automatically
  - **People discussed** — seed the people graph from AI conversations
  - **Priority signals** — "this is urgent," "let's do X first," "defer Y"
  - **Knowledge/context** — what the user learned or established as fact

**Step 4: Richer extraction prompt for AI conversations**
- Current `DECISION_EXTRACTION_SYSTEM` only pulls decisions
- New prompt should extract a full structured record:

```json
{
  "decisions": [...],
  "projects_discussed": ["focus", "auth-service"],
  "people_mentioned": ["Sarah", "John"],
  "priorities_stated": ["finish auth before API", "ship by Friday"],
  "questions_explored": ["how should we handle rate limiting?"],
  "knowledge_established": ["PostgreSQL handles our scale fine"],
  "mood": "focused",
  "session_type": "implementation"  // vs "planning", "debugging", "research", "brainstorming"
}
```

### Config changes

```toml
[ai_capture]
claude_web_export = "~/Downloads/claude_export.json"  # path to export file
chatgpt_export = "~/Downloads/chatgpt_export.json"
auto_capture_claude_code = true  # already true via daemon
extract_from_conversations = true
```

### This solves onboarding

The cold-start problem disappears. Instead of waiting for emails to slowly build context, import your AI conversation history and Focus immediately knows:
- What projects you care about
- Who you work with
- What you've decided
- What your priorities are
- What technical context matters

---

## Phase 2 — Machine Monitoring

**Goal:** Know what you're working on across all machines, automatically.

### What to install

| Machine | Install | Why |
|---------|---------|-----|
| Both | [ActivityWatch](https://activitywatch.net/) | Window title + app tracking (open source, local) |
| Both | Focus daemon | Already built, just needs to run on both |

```bash
# Install ActivityWatch (Arch)
yay -S activitywatch-bin
# Or pip: pip install aw-server aw-watcher-window aw-watcher-afk

# Start it
aw-server &
aw-watcher-window &
aw-watcher-afk &
```

### New code to write

| File | What | Effort |
|------|------|--------|
| `src/ingestion/activitywatch.py` | Poll AW REST API (localhost:5600), store window events as raw_interactions | Small |
| `src/ingestion/git_activity.py` | Scan configured repos for commits, map repo → project | Small |
| `src/ingestion/shell_history.py` | Parse ~/.zsh_history with timestamps | Small |

### DB changes

```sql
ALTER TABLE raw_interactions ADD COLUMN machine_id TEXT;
-- New source_type values: "activitywatch", "git_commit", "shell_command"
```

### Config changes

```toml
[monitoring]
activitywatch_url = "http://localhost:5600"
git_repos = ["~/code/*", "~/projects/*"]
shell_history = true
machine_id = "laptop"  # unique per machine
```

### Multi-machine setup

Both machines point at the same PostgreSQL over LAN:

```
Laptop → postgresql+asyncpg://192.168.1.X/focus
Desktop → postgresql+asyncpg://192.168.1.X/focus
```

Options:
- **Direct LAN** — expose postgres on LAN IP (edit `pg_hba.conf` + `postgresql.conf`)
- **SSH tunnel** — `ssh -L 5432:localhost:5432 desktop` (more secure, no pg config changes)
- **Tailscale** — both machines on tailnet, connect via Tailscale IP (easiest + secure)

Content-hash dedup handles any overlap.

### Daily activity summary

New section in TODAY.md: "What I worked on" — aggregated from AW + git + shell + AI conversations across machines. Auto-detect project context switches. Show time breakdown by project.

---

## Phase 3 — iOS Integration

No daemon possible on iOS. Use these channels instead:

### A. iOS Shortcuts → Focus API (fastest to ship)

1. Expose the Focus API via **Tailscale** on your LAN
2. Build iOS Shortcuts that POST to it:
   - "Log what I'm working on" → `POST /api/capture` with text
   - "Start focus session" → logs work block start with project tag
   - "End focus session" → logs end, calculates duration
   - Auto-triggers: arrive at location, connect to WiFi, open an app

**Setup needed:**
- Install Tailscale on your machines + iPhone
- Run `uvicorn src.api.routes:app --host 0.0.0.0 --port 8000` (or via daemon)
- Create Shortcuts on iPhone that hit `http://<tailscale-ip>:8000/...`

### B. Screen Time data (free, via Mac)

Screen Time syncs iOS app usage to macOS via iCloud. The data lives at:

```
~/Library/Application Support/Knowledge/knowledgeC.db
```

Ingest this SQLite DB on the Mac side — gives you iOS app usage for free.
Maps app names → project context (Slack = communication, Xcode = coding, etc.)

### C. iCloud-synced data (free, via Mac)

- **Safari history** — syncs to Mac, readable from SQLite
- **Reminders** — accessible via macOS EventKit or `reminders` CLI
- **Notes** — synced, readable from macOS
- **Calendar** — accessible via Google Calendar API or macOS EventKit

### D. Future: Focus mobile dashboard

- PWA or native app showing TODAY.md
- Quick capture: tap to log a thought, task, or work session
- Push notifications for commitments due

---

## Phase 4 — Zoom / Audio Notetaker

Ingest Zoom recordings or raw audio files:

1. Transcribe via **Whisper** (local or API)
2. Run transcript through the extraction pipeline
3. Pull out tasks, commitments, decisions, people mentioned
4. Auto-link to calendar events for meeting context

**Setup:** Install `openai-whisper` or use the API. Add `src/ingestion/audio.py`.

---

## Phase 5 — Advanced Processing

### Smarter classification over time

- Build a per-user sender reputation score (auto-learn who's always spam)
- Track cost savings from pre-filtering vs. LLM classification

### Full prompt/response audit

Partially done (ai_conversations table). Verify end-to-end:
- Every classifier call logged with full prompt + response
- Every extractor call logged
- Token counts and costs tracked
- Which email/conversation triggered each call

### iMessage ingestion (F-015)

macOS only. Read `~/Library/Messages/chat.db`:
- Parse message threads
- Extract tasks/commitments from text conversations
- Link to known people

---

## Architecture: Where It's All Going

```
                          ┌──────────────────────────────────────┐
                          │          Focus DB (PostgreSQL)        │
                          │        One DB, all machines           │
                          └──────┬──────────────────┬────────────┘
                                 │                  │
                 ┌───────────────┴──┐        ┌──────┴──────────────┐
                 │   Laptop daemon  │        │   Desktop daemon    │
                 │                  │        │                     │
                 │  AI CONVERSATIONS│        │  AI CONVERSATIONS   │
                 │  ├ Claude Code   │        │  ├ Claude Code      │
                 │  ├ Claude.ai *   │        │  ├ Claude.ai *      │
                 │  └ ChatGPT *     │        │  └ ChatGPT *        │
                 │                  │        │                     │
                 │  PASSIVE INPUT   │        │  PASSIVE INPUT      │
                 │  ├ Gmail sync    │        │  ├ Gmail sync       │
                 │  ├ Drive sync    │        │  ├ Drive sync       │
                 │  ├ ActivityWatch │        │  ├ ActivityWatch    │
                 │  ├ Git watcher   │        │  ├ Git watcher      │
                 │  ├ Shell history │        │  ├ Shell history    │
                 │  └ iMessage *    │        │  └ Browser hist *   │
                 └──────────────────┘        └─────────────────────┘
                                 │                  │
                                 ▼                  ▼
                 ┌──────────────────────────────────────────────────┐
                 │              Processing Pipeline                 │
                 │                                                  │
                 │  AI convos → extract decisions, projects,        │
                 │              priorities, people, knowledge       │
                 │                                                  │
                 │  Emails   → pre-filter → classify → extract →   │
                 │              resolve → index                     │
                 │                                                  │
                 │  Activity → map windows/commits/commands →       │
                 │              project time tracking               │
                 └──────────────────────────────────────────────────┘
                                 │
                 ┌───────────────┼───────────────┐
                 ▼               ▼               ▼
           Obsidian Vault   CLAUDE.md      REST API
           (local files)    (project root)  (Tailscale)
                                                 │
                                                 ▼
                                           iOS Shortcuts
                                           Mobile dashboard
```

\* = not yet built

---

## Priority Order

1. **Reset + re-sync** — immediate, 5 min, fixes classification quality
2. **Claude.ai + ChatGPT history import** — the biggest bang: months of decisions, projects, and priorities in one shot
3. **Richer AI conversation extraction** — expand beyond just "decisions" to capture projects, people, priorities, knowledge
4. **ActivityWatch** — install and write the ingestion module for passive monitoring
5. **Multi-machine postgres** — set up Tailscale between machines
6. **iOS Shortcuts** — expose API via Tailscale, build 2-3 Shortcuts
7. **Zoom/audio** — when you start having meetings to capture
8. **iMessage** — when you're on macOS and want text conversations

The theme: **what you tell AI > what other people email you.** Build capture for active direction first, passive input second.

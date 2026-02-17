# Focus

**Your second brain that actually builds itself.**

Zero manual entry. Connect your accounts, wait 10 minutes, get a fully populated knowledge base with tasks, commitments, people, projects, and priorities — all extracted automatically from your actual communications.

## The Problem

Every AI assistant now has "memory." Claude remembers your preferences. ChatGPT references past conversations. Copilot learns your working style. But they all share the same fundamental limitation: **they only remember what you told them.**

Your real knowledge isn't in AI chat logs. It's scattered across email threads, document edits, text messages, code sessions, and meeting notes. No AI system connects these sources, extracts structured knowledge, and builds a self-organizing picture of your work.

Focus does.

## How It Works

```
Gmail / Drive / Claude Code sessions
         │
         ▼
   ┌─────────────┐     ┌──────────────┐     ┌─────────────┐
   │  Classify    │ ──▶ │   Extract    │ ──▶ │   Resolve   │
   │  (Ollama $0) │     │  (Haiku ~$0) │     │  (fuzzy $0) │
   └─────────────┘     └──────────────┘     └─────────────┘
                                                    │
                              ┌──────────────────────┤
                              ▼                      ▼
                     ┌─────────────┐        ┌──────────────┐
                     │  PostgreSQL │        │    Chroma     │
                     │  (18 tables)│        │ (vector search│
                     └──────┬──────┘        └──────────────┘
                            │
              ┌─────────┬───┴───┬──────────┐
              ▼         ▼       ▼          ▼
         Obsidian   CLAUDE.md  Kanban   Daily Notes
          Vault    (auto-gen)  Boards
```

**Tiered cost optimization.** Classification runs on a local LLM (Ollama + Qwen3 4B) for $0. Automated emails are parsed with regex for $0. Only human emails hit Claude Haiku at ~$0.0003 each. Entity resolution uses fuzzy matching for $0.

**Raw data is the real asset.** Every email, document, and conversation is stored permanently in its original form. Today's extraction is only as good as today's models. When better models arrive, reprocess everything with one command.

## What Gets Extracted

From a single email like *"Hey, can you review the API spec by Friday? Sarah mentioned the auth team needs it for the v2 launch"* — Focus extracts:

- **Task:** Review API spec (deadline: Friday, assigned: you)
- **Commitment:** Deliver reviewed spec by Friday
- **People:** Sarah, auth team
- **Project:** v2 launch (auto-created or linked to existing)
- **Priority:** High (deadline within a week)

Multiply this across hundreds of emails, and you get a knowledge graph that would take weeks to build manually.

## What You Get

**Obsidian Vault** — A self-organizing markdown vault:
```
Focus-Vault/
├── Projects/
│   └── v2-launch/
│       ├── KANBAN.md          # Task board
│       ├── PEOPLE.md          # Who's involved
│       ├── DECISIONS.md       # What was decided
│       ├── EMAILS.md          # Relevant threads
│       └── TIMELINE.md        # Project history
├── People/
│   └── Sarah.md               # Everything about Sarah
├── Daily/
│   └── 2026-02-17.md          # Today's tasks, emails, commitments
├── Me/
│   ├── Commitments.md         # What you owe people
│   └── Preferences.md         # Your stated preferences
└── Inbox/
    └── EMAIL-DRAFTS.md        # Suggested replies, ranked by urgency
```

**CLAUDE.md** — An auto-generated project briefing that loads into every Claude Code session. Contains your architecture, conventions, current sprint, active blockers, and people context. Your AI coding assistant always knows what you're working on.

**REST API** — Full CRUD + sync/generate/search endpoints. Build whatever frontend you want.

## Features (19/20 shipped)

| # | Feature | Status |
|---|---------|--------|
| F-001 | Gmail ingestion (OAuth, incremental sync) | Done |
| F-002 | Google Drive ingestion (Changes API, text export) | Done |
| F-003 | Multi-account email (per-account OAuth, priority weights) | Done |
| F-004 | Email classification (Ollama local LLM, rules-based fast path) | Done |
| F-005 | Deep extraction (tasks, commitments, people, projects via Haiku) | Done |
| F-006 | Regex parsing (orders, tracking numbers, amounts from automated email) | Done |
| F-007 | Entity resolution (fuzzy-match people + projects, auto-create) | Done |
| F-008 | Obsidian vault generation (full directory structure) | Done |
| F-009 | CLAUDE.md generation (auto project briefing) | Done |
| F-010 | User priority system (pin, deadlines, effective scoring) | Done |
| F-011 | Sprints (time-bounded priority boosts, auto-archive) | Done |
| F-012 | Raw interaction archive (permanent storage, content-hash dedup) | Done |
| F-013 | Reprocessing pipeline (re-extract with current models) | Done |
| F-014 | Email draft queue (suggested replies sorted by urgency) | Done |
| F-015 | iMessage ingestion | Planned |
| F-016 | Daemon mode (background sync loop, SIGINT/SIGTERM) | Done |
| F-017 | REST API (FastAPI, full CRUD + triggers) | Done |
| F-018 | Semantic search (Chroma vector DB, cosine similarity) | Done |
| F-019 | Claude Code session capture (JSONL parsing, decision extraction) | Done |
| F-020 | Claude Code skills system (auto-generate, search, install, context injection) | Done |

## Quick Start

```bash
# Clone and set up
git clone https://github.com/nathansimon/focus.git
cd focus
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# Initialize database and config
focus init

# Connect your Gmail
focus account add    # Opens browser for OAuth

# Sync and generate
focus sync           # Fetch → classify → extract → resolve
focus generate       # Build Obsidian vault + CLAUDE.md

# Open ~/Focus-Vault/ in Obsidian
```

### Requirements

- Python 3.11+
- PostgreSQL (running)
- Ollama with `qwen3:4b` model (for local classification)
- Anthropic API key (for extraction via Haiku)
- Google Cloud project with Gmail + Drive APIs enabled

### Run Continuously

```bash
focus daemon              # Sync every 15 minutes, auto-regenerate vault
focus daemon --interval 5 # Or every 5 minutes
```

## CLI

```
focus sync              Fetch emails + Drive docs, classify, extract, resolve
focus generate          Rebuild Obsidian vault + CLAUDE.md
focus search TEXT       Search across all data
focus search TEXT -s    Semantic search (by meaning, not keywords)
focus status            Data counts and sync state
focus priorities        Ranked project priorities

focus account add|list|auth|enable|disable|priority
focus project list|pin|unpin|priority|deadline|archive
focus task    list|create|status|priority|assign
focus sprint  create|list|deactivate

focus capture           Extract decisions from Claude Code sessions
focus record            Record Claude Code session transcripts
focus reprocess         Re-extract data with current models
focus daemon            Background sync loop
```

## Architecture

```
src/
├── ingestion/          # Data connectors
│   ├── gmail.py        # OAuth + incremental sync via historyId
│   ├── drive.py        # Changes API + text export
│   ├── accounts.py     # Multi-account management
│   └── claude_code.py  # Session JSONL parser
├── processing/         # Tiered AI pipeline
│   ├── classifier.py   # Ollama Qwen3 4B (local, $0)
│   ├── extractor.py    # Claude Haiku (tasks, people, commitments)
│   ├── regex_parser.py # Orders, tracking, amounts ($0)
│   └── resolver.py     # Entity resolution + project linking
├── storage/            # Data layer
│   ├── db.py           # PostgreSQL via SQLAlchemy (async)
│   ├── models.py       # ORM models (18 tables)
│   ├── vectors.py      # Chroma vector store
│   └── raw.py          # Permanent raw archive
├── output/             # Markdown generation
│   ├── vault.py        # Obsidian vault structure
│   ├── kanban.py       # Per-project task boards
│   ├── daily.py        # Daily notes
│   ├── drafts.py       # Email reply suggestions
│   └── claude_md.py    # Auto-generated CLAUDE.md
├── context/            # Claude Code context system
│   ├── classifier.py   # Prompt classification
│   ├── retriever.py    # Context retrieval from DB
│   ├── formatter.py    # Token-budget-aware formatting
│   └── worker.py       # Background job processor
├── api/routes.py       # FastAPI REST endpoints
├── cli/                # Typer CLI (14 subcommands)
├── daemon.py           # Background sync loop
├── priority.py         # Priority scoring engine
└── config.py           # Settings (TOML config)
```

**Key patterns:** Async throughout. SQLAlchemy 2.0 with `selectinload()`. Pydantic models for all data boundaries. Content-hash dedup on all ingestion. Every AI call logged with tokens, cost, and latency.

## Testing

665+ tests covering every module. All external dependencies mocked.

```bash
pytest tests/ -x -q
```

## Design Principles

1. **User intent over AI inference.** Auto-organize, but user pins, deadlines, and priority boosts always win.
2. **Raw data is the real asset.** Structured views are disposable; raw interactions are forever. Reprocess with better models anytime.
3. **Temporal awareness.** A GRE exam on Friday dominates everything until it's done, then becomes irrelevant. The system understands time-bounded urgency.
4. **Tiered cost control.** Local LLM for classification ($0), regex for parsing ($0), Haiku for extraction (~$0.0003/email). Every dollar accounted for.
5. **Local-first.** Your data lives on your hardware. No cloud dependency for storage. No vendor lock-in.

---

# Future Directions

## Where AI Memory Is Today

Every major AI provider shipped memory features in 2025. Here's what exists:

| System | How It Works | Limitation |
|--------|-------------|------------|
| **Claude.ai** | Auto-synthesizes conversations every ~24 hours, per-project scoping | Lossy summaries, no external data, cloud-only |
| **Claude Code** | CLAUDE.md files at project root, read at session start | Manual authoring, no cross-session context |
| **ChatGPT** | Saved facts + passive chat history referencing (April 2025) | Global scope (no per-project), cloud-only, opaque storage |
| **Gemini** | Learns from past conversations, planned cross-app recall | Cloud-only, no structured extraction |
| **Copilot (M365)** | Preferences + Work IQ across M365 graph | Locked to Microsoft ecosystem |
| **GitHub Copilot** | Saves memories as editable markdown in repo | Coding context only |
| **Anthropic Memory API** | Client-side tool, developer-controlled storage | Beta, no ingestion pipeline |

**The common thread:** They all remember what you told them. None of them go get information you didn't provide. None of them ingest your email, extract your commitments, track your deadlines, or build a knowledge graph from your actual communications.

Focus occupies the gap between *reactive recall* (remembering preferences) and *proactive extraction* (building structured knowledge from raw data).

## What's Next

### Phase 1: Automatic Context System

The context infrastructure is half-built. The goal: Claude Code sessions automatically receive relevant context from Focus's database, and every session is automatically recorded back. The user never has to think about it.

**How it works:**
- **UserPromptSubmit hook** — Before Claude responds, Focus classifies the prompt, retrieves relevant past conversations/emails/decisions, and injects them via `additionalContext`. Completes in <2 seconds.
- **Stop hook** — After Claude responds, Focus enqueues the transcript for background recording. Completes in <200ms.
- **Background worker** — Parses JSONL, stores raw turns, generates summaries, extracts entities, links to projects.

This is system-driven, not agent-driven. The agent never needs to know the context system exists — it just always has the right background knowledge. This is fundamentally different from OneContext (agent must invoke a skill) and GCC (agent must call CONTEXT).

### Phase 2: AI Conversation Import

The cold-start problem disappears when you import existing AI conversation history.

- **Claude.ai web export** — Parse JSON export, extract decisions/projects/people/priorities
- **ChatGPT export** — Same extraction, different format
- **Enhanced Claude Code capture** — Beyond decisions: extract projects worked on, people discussed, priority signals, knowledge established

One import seeds the project graph, decision log, and people graph with months of real context. Emails build slowly over time; AI conversations deliver the entire picture immediately.

### Phase 3: Machine Monitoring

Know what you're working on across all machines, automatically.

- **ActivityWatch integration** — Open-source window/app tracking, ingested via local REST API
- **Git activity** — Scan configured repos for commits, auto-map to projects
- **Shell history** — Parse with timestamps, detect active project context
- **Multi-machine sync** — Both machines point at same PostgreSQL over Tailscale/LAN
- **Daily activity summary** — "What I worked on" section in daily notes, aggregated across machines

### Phase 4: Source Expansion

- **iMessage** (macOS) — Read `~/Library/Messages/chat.db`, extract tasks/commitments from texts
- **Calendar integration** — Meeting context, prep notes, follow-up extraction
- **Slack/Discord** — Extend the pipeline to team chat
- **Zoom/audio** — Whisper transcription → extraction pipeline
- **PDF/attachment extraction** — Process Drive attachments, not just metadata

### Phase 5: Intelligence Layer

- **Commitment tracker with nudges** — Surface overdue commitments: "You promised X to Y, 3 days ago"
- **Relationship intelligence** — "You haven't emailed Alex in 2 weeks; last topic was the contract review"
- **Priority decay/surge** — Auto-adjust based on email velocity, approaching deadlines, stale tasks
- **Proactive briefings** — Morning note with today's commitments, meetings, stale tasks, draft replies
- **Multi-LLM routing** — Simple emails → Haiku, complex → Sonnet, sensitive → local-only Ollama

### Phase 6: Interfaces

- **Web dashboard** — React frontend for project overview, email triage, priority management
- **Mobile view** — PWA for reading daily notes and quick capture on phone
- **iOS Shortcuts** — POST to Focus API via Tailscale for on-the-go capture

## What Focus Does That Nothing Else Does

| Capability | Focus | Cloud AI Memory |
|-----------|-------|-----------------|
| Ingests email, docs, code sessions | Yes | No — only chat history |
| Extracts tasks, commitments, deadlines | Yes | No — only preferences/facts |
| Entity resolution across months of data | Yes | No — no entity graph |
| Stores raw data for reprocessing | Yes | No — lossy summaries only |
| Transparent, inspectable, version-controlled | Yes (Obsidian + git) | No — opaque cloud storage |
| Tiered cost control per processing stage | Yes ($0 local + ~$0.0003 Haiku) | No — opaque token consumption |
| Works offline | Yes (local LLM + PostgreSQL) | No |
| Per-project context scoping | Yes | Partial (Claude only) |
| Temporal priority awareness (sprints, deadlines) | Yes | No |
| Cross-source knowledge graph | Yes | No |

The thesis: **what you tell AI systems > what other people email you.** AI conversations are the highest-signal input Focus will ever see — direct statements of intent, decisions, priorities, and knowledge. Email is context. AI conversations are direction. Build for both, but prioritize direction.

## Simon — Standalone Memory for Claude Code

The memory and context system is available as a standalone tool: **[Simon](https://github.com/nathanasimon/simon)**

```bash
npm install -g simon-memory
```

Simon records your Claude Code sessions, injects relevant context into every new prompt, and auto-generates reusable skills — without needing the full Focus stack. Works with any project.

## License

MIT

## Contributing

Focus is a personal project in active development. Issues and PRs welcome.

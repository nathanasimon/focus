# Focus — Claude Code Specification

> **"Your second brain that actually builds itself."**
> Zero manual entry. Connect accounts → wait 10 minutes → fully populated Obsidian vault.

---

## What You're Building

A local-first, AI-powered personal knowledge management system that:

1. **Ingests** email (multiple accounts), texts, cloud docs, and Claude Code sessions
2. **Classifies** content with a free local LLM (human vs automated vs spam)
3. **Extracts** structured data (tasks, commitments, people, projects) via Claude Haiku
4. **Stores raw interactions permanently** — every conversation, every extraction, every version — so the system gets smarter as models improve
5. **Lets users set priorities** — pin important projects, set deadlines, define what matters *right now*
6. **Generates** a self-organizing Obsidian vault with Kanban boards, email drafts, and CLAUDE.md files

**Primary use case (MVP):** Perfect context for Claude Code across all your projects.

### Design Principles

- **User intent over AI inference.** The system auto-organizes, but users can always override. Pinned projects, manual deadlines, and priority boosts take precedence over algorithmic scoring.
- **Raw data is the real asset.** Today's extraction is only as good as today's models. Store every raw interaction permanently so you can re-process with better models later. The structured views are disposable; the raw data is forever.
- **Temporal awareness.** Not all tasks are equal. A GRE exam on Feb 13 dominates everything until it's done, then becomes irrelevant. The system must understand time-bounded urgency natively.
- **Features are documented or they don't exist.** Every feature has an entry in `FEATURES.md`. If it's not in the registry, it's not a feature — it's a bug waiting to happen.

---

## Feature Registry

This project can easily spiral. Every feature must be documented in `docs/FEATURES.md` at the project root. This is a hard rule: **no feature gets built without a registry entry, and no feature gets changed without updating its entry.**

### Why This Matters

Focus has a lot of moving parts — ingestion, classification, extraction, entity resolution, priority scoring, vault generation, CLAUDE.md generation, sprints, multi-account email, raw storage, reprocessing. Without a single document that says "here is every feature, what it does, what state it's in, and what it depends on," the project will drift. Features will half-work, overlap, or contradict each other.

### FEATURES.md Format

Every feature gets a block in this format:

```markdown
# Focus — Feature Registry

> This file is the single source of truth for what Focus does.
> Every feature is listed here. If it's not here, it doesn't exist.
> Update this file BEFORE building or changing any feature.

Last updated: 2026-02-05
Total features: 19 (9 MVP, 10 post-MVP)

---

## F-001: Gmail Ingestion
- **Status**: BUILDING | MVP
- **Phase**: 1 (Foundation)
- **What**: Connect to Gmail via OAuth, fetch emails incrementally using historyId
- **Inputs**: Google OAuth credentials, email account config
- **Outputs**: Raw emails in `raw_interactions` + processed rows in `emails` table
- **Depends on**: F-003 (Multi-Account Email)
- **Depended on by**: F-004 (Classification), F-005 (Extraction)
- **Key files**: `src/ingestion/gmail.py`
- **Notes**: Supports multiple accounts. Each account has its own OAuth token and sync cursor.

## F-002: Google Drive Ingestion
- **Status**: PLANNED | MVP
- **Phase**: 2 (Core Features)
- **What**: Sync documents from Google Drive via Changes API
- **Inputs**: Google OAuth credentials (shared with Gmail)
- **Outputs**: Raw docs in `raw_interactions` + processed rows in `documents` table
- **Depends on**: F-003 (Multi-Account Email, for shared OAuth)
- **Depended on by**: F-008 (Vault Generation)
- **Key files**: `src/ingestion/drive.py`

## F-003: Multi-Account Email
- **Status**: BUILDING | MVP
- **What**: Support multiple email accounts with per-account priority weights and processing rules
- **Inputs**: User adds accounts via `focus account add`
- **Outputs**: `email_accounts` table rows, per-account OAuth tokens
- **Depends on**: Nothing
- **Depended on by**: F-001 (Gmail), F-002 (Drive), F-010 (Priority Scoring)
- **Key files**: `src/ingestion/accounts.py`, `src/cli/account.py`
- **Config**: `accounts.toml` or DB-managed via CLI

## F-004: Email Classification
- **Status**: PLANNED | MVP
- **What**: Classify emails as human/automated/newsletter/spam/system using local LLM
- **Inputs**: Raw email from ingestion
- **Outputs**: Classification label + confidence + routing decision
- **Depends on**: F-001 (Gmail Ingestion)
- **Depended on by**: F-005 (Extraction), F-006 (Regex Parse)
- **Key files**: `src/processing/classifier.py`
- **Model**: Ollama + Qwen3 4B ($0, <100ms)

## F-005: Deep Extraction (Human Emails)
- **Status**: PLANNED | MVP
- **What**: Extract tasks, commitments, questions, people, projects from human emails
- **Inputs**: Human-classified emails + known projects/people context
- **Outputs**: Structured extraction JSON → tasks, commitments, people tables
- **Depends on**: F-004 (Classification)
- **Depended on by**: F-007 (Entity Resolution), F-008 (Vault), F-009 (CLAUDE.md)
- **Key files**: `src/processing/extractor.py`
- **Model**: Claude Haiku (~$0.0003/email)

## F-006: Regex Parse (Automated Emails)
- **Status**: PLANNED | MVP
- **What**: Extract order numbers, tracking, amounts from automated emails
- **Inputs**: Automated-classified emails
- **Outputs**: Structured data in `emails.extraction_result`
- **Depends on**: F-004 (Classification)
- **Depended on by**: F-008 (Vault — Automated inbox view)
- **Key files**: `src/processing/regex_parser.py`

## F-007: Entity Resolution
- **Status**: PLANNED | MVP
- **What**: Fuzzy-match people and projects across sources, dedup, create new entities
- **Inputs**: Extraction results with raw names/references
- **Outputs**: Linked foreign keys in tasks, commitments, emails tables
- **Depends on**: F-005 (Extraction)
- **Depended on by**: F-008 (Vault), F-009 (CLAUDE.md)
- **Key files**: `src/processing/resolver.py`

## F-008: Obsidian Vault Generation
- **Status**: PLANNED | MVP
- **What**: Generate the full vault directory structure from DB state
- **Inputs**: All DB tables
- **Outputs**: Markdown files in vault/ (README, KANBAN, PEOPLE, DECISIONS, etc.)
- **Depends on**: F-005, F-006, F-007
- **Depended on by**: F-009 (CLAUDE.md references vault paths)
- **Key files**: `src/output/vault.py`, `src/output/kanban.py`, `src/output/daily.py`
- **Generates**: Project folders, person files, inbox views, daily notes

## F-009: CLAUDE.md Generation
- **Status**: PLANNED | MVP
- **What**: Generate machine-readable project briefing at project root
- **Inputs**: DB state (tasks, decisions, people, sprints, preferences)
- **Outputs**: CLAUDE.md at project root
- **Depends on**: F-005, F-007, F-010
- **Depended on by**: Nothing (end of chain, consumed by Claude Code)
- **Key files**: `src/output/claude_md.py`
- **Regeneration triggers**: sync, generate, sprint change, priority change

## F-010: User Priority System
- **Status**: PLANNED | Post-MVP
- **What**: User-set pins, priorities, deadlines that override AI scoring
- **Inputs**: CLI commands (focus project pin, focus task priority, etc.)
- **Outputs**: Updated project/task rows, effective priority recalculation
- **Depends on**: F-003 (account weights)
- **Depended on by**: F-009 (CLAUDE.md), F-008 (daily notes)
- **Key files**: `src/cli/priority.py`, `src/priority.py`

## F-011: Sprints
- **Status**: PLANNED | Post-MVP
- **What**: Time-bounded priority boosts with auto-archive on expiry
- **Inputs**: CLI (focus sprint create/list/deactivate)
- **Outputs**: `sprints` table rows, priority multipliers, auto-archive actions
- **Depends on**: F-010 (Priority System)
- **Depended on by**: F-009 (CLAUDE.md shows active sprint)
- **Key files**: `src/cli/sprint.py`, `src/sprint.py`

## F-012: Raw Interaction Archive
- **Status**: PLANNED | MVP
- **What**: Store every raw interaction permanently for future reprocessing
- **Inputs**: All ingested data (emails, messages, docs, AI calls)
- **Outputs**: `raw_interactions` table, `ai_conversations` table
- **Depends on**: Nothing
- **Depended on by**: F-013 (Reprocessing)
- **Key files**: `src/storage/raw.py`

## F-013: Reprocessing Pipeline
- **Status**: PLANNED | Post-MVP
- **What**: Re-extract structured data from raw interactions using current/better models
- **Inputs**: Raw interactions + new model/prompt version
- **Outputs**: Updated extraction results, refreshed structured tables
- **Depends on**: F-012 (Raw Archive)
- **Depended on by**: Nothing
- **Key files**: `src/processing/reprocess.py`
- **CLI**: `focus reprocess --since DATE`

## F-014: Email Draft Queue
- **Status**: PLANNED | Post-MVP
- **What**: Suggest email replies based on extraction + user style
- **Inputs**: Emails needing reply + user communication style per person
- **Outputs**: EMAIL-DRAFTS.md in vault
- **Depends on**: F-005 (Extraction)
- **Depended on by**: F-008 (Vault)
- **Key files**: `src/output/drafts.py`

## F-015: iMessage Ingestion
- **Status**: PLANNED | Post-MVP
- **What**: Read iMessage SQLite DB on macOS
- **Inputs**: ~/Library/Messages/chat.db
- **Outputs**: Messages in `messages` table + `raw_interactions`
- **Depends on**: Nothing (but macOS only)
- **Key files**: `src/ingestion/imessage.py`

## F-016: Daemon Mode
- **Status**: PLANNED | Post-MVP
- **What**: Run continuously, syncing and regenerating on interval
- **Inputs**: Config (sync interval)
- **Outputs**: Periodic sync + vault regeneration
- **Depends on**: F-001, F-008, F-009
- **Key files**: `src/daemon.py`
- **CLI**: `focus daemon`

## F-017: REST API
- **Status**: PLANNED | Post-MVP
- **What**: FastAPI endpoints for querying data, triggering syncs
- **Inputs**: HTTP requests
- **Outputs**: JSON responses
- **Depends on**: All storage features
- **Key files**: `src/api/`

## F-018: Semantic Search
- **Status**: PLANNED | Post-MVP
- **What**: Search across all data using Chroma vector embeddings
- **Inputs**: Query string
- **Outputs**: Ranked results from emails, docs, projects
- **Depends on**: F-012 (Raw Archive), Chroma
- **Key files**: `src/storage/vectors.py`
- **CLI**: `focus search "query"`

## F-019: Claude Code Session Capture
- **Status**: PLANNED | Post-MVP
- **What**: Hook into Claude Code sessions to capture decisions and context
- **Inputs**: Claude Code session output
- **Outputs**: Decisions in DECISIONS.md, context updates
- **Depends on**: F-009 (CLAUDE.md)
- **Key files**: `src/ingestion/claude_code.py`
```

### Feature Registry Rules

1. **Before building**: Add the feature entry to FEATURES.md with status `PLANNED`
2. **While building**: Update status to `BUILDING`, fill in key files as they're created
3. **When done**: Update status to `DONE`, verify all dependency links are correct
4. **When changing**: Update the entry FIRST, then change the code. If the change affects dependencies, update those entries too.
5. **When removing**: Don't delete the entry — mark it `REMOVED` with a note explaining why

### Status Values

| Status | Meaning |
|--------|---------|
| `PLANNED` | Designed but not started |
| `BUILDING` | Actively being built |
| `DONE` | Working, tested, documented |
| `REFACTORING` | Working but being reworked |
| `REMOVED` | Deprecated or removed (keep entry for history) |
| `PAUSED` | Started but on hold |

### Dependency Tracking

Every feature lists what it depends on and what depends on it. This makes it immediately obvious when changing one feature what else might break. The generator for CLAUDE.md (F-009) depends on extraction (F-005), entity resolution (F-007), and priorities (F-010) — so if any of those change, CLAUDE.md generation probably needs updating too.

### Updating the Registry

The registry is a markdown file that Claude Code can read. When you ask Claude Code to build or change a feature, it should:
1. Read `docs/FEATURES.md` first
2. Check dependencies
3. Update the entry
4. Build/change the code
5. Verify no dependent features broke

---

## Architecture Overview

```
Data Sources (Gmail ×N accounts, Drive, iMessage, Claude Code sessions)
        │
        ▼
Ingestion Layer (OAuth per account, SQLite read, incremental sync, dedup)
        │
        ├──→ RAW STORAGE (permanent archive — every interaction verbatim)
        │    └── Raw emails, messages, docs, AI conversations, extraction snapshots
        │
        ▼
Tiered Processing
  ├── Stage 1: Classification — Ollama + Qwen3 4B ($0, <100ms)
  │   └── Route: human → deep analysis, automated → regex parse
  ├── Stage 2a: Deep Analysis — Claude Haiku (~$0.0003/email)
  │   └── Extract: tasks, commitments, questions, projects, people, reply drafts
  ├── Stage 2b: Quick Parse — Regex ($0)
  │   └── Extract: order numbers, tracking, amounts, dates
  └── Stage 3: Entity Resolution
      └── Fuzzy-match people, link to projects, create new entities
        │
        ▼
User Priority Layer (manual overrides take precedence)
  ├── Pinned projects + user-set deadlines
  ├── Sprint (time-bounded priorities like "GRE prep until Feb 13")
  ├── Per-account priority weights
  └── Effective priority = f(user_priority, deadline_urgency, AI_score)
        │
        ▼
Hybrid Storage
  ├── PostgreSQL — source of truth, queries, audit log, relations
  ├── Chroma — vector embeddings, semantic search
  └── Markdown — human interface, generated from DB
        │
        ▼
Output Layer
  ├── Obsidian vault (auto-organized)
  ├── Per-project Kanban boards
  ├── Email draft queue with suggested replies
  ├── CLAUDE.md files for Claude Code
  └── REST API (FastAPI)
```

---

## Tech Stack

| Component       | Technology                | Notes                                    |
|-----------------|---------------------------|------------------------------------------|
| Language        | Python 3.11+              | Async throughout (asyncio)               |
| Web Framework   | FastAPI                   | REST API, auto-docs                      |
| Database        | PostgreSQL                | JSONB, full-text search, encrypted       |
| Vector DB       | Chroma                    | Local-first, cosine similarity           |
| Local LLM       | Ollama + Qwen3 4B         | Classification only, free                |
| Cloud LLM       | Anthropic API (Haiku)     | Extraction, drafts — user provides key   |
| Task Queue      | Celery + Redis            | Background processing                    |
| Output          | Markdown / Obsidian       | Portable, human-readable                 |
| Deployment      | Docker (optional)         | Local dev first, containerize later      |

---

## Data Sources & Ingestion

### Multi-Account Email Support

Users have multiple email lives — work, personal, school, side projects. The system treats each account as a separate source with its own priority weight and processing rules.

```toml
# Example: config/accounts.toml

[[accounts]]
name = "personal"
type = "gmail"
email = "nathan@gmail.com"
priority_weight = 1.0          # Normal priority
sync_enabled = true
process_newsletters = false     # Skip marketing emails

[[accounts]]
name = "school"
type = "gmail"
email = "nathan@newschool.edu"
priority_weight = 1.5          # Boost school emails (GRE, applications, etc.)
sync_enabled = true
process_newsletters = true

[[accounts]]
name = "work"
type = "gmail"
email = "nathan@company.com"
priority_weight = 2.0          # Work emails always high priority
sync_enabled = true
process_newsletters = false
```

Each account gets its own OAuth token. Email-to-project routing can use account as a signal (school emails → academic projects, work emails → work projects).

### MVP Sources

#### 1. Gmail (multiple accounts)
- **Auth:** Google OAuth 2.0 per account
- **Sync:** Incremental via `historyId` per account
- **Extracts:** Full body (human emails), headers, timestamps, thread structure, labels, attachment metadata
- **Account field:** Every email record tracks which account it came from

#### 2. Google Drive
- **Auth:** Same Google OAuth (shared credentials per account)
- **Sync:** Changes API with `pageToken`
- **Extracts:** Document text (Docs/Sheets), metadata, comments, folder structure

#### 3. iMessage / SMS (macOS only)
- **Method:** Direct SQLite read from `~/Library/Messages/chat.db`
- **Requires:** Full Disk Access permission
- **Extracts:** Message content, timestamps, sender/recipient, group chat context

#### 4. Claude Code Sessions (future — Week 6+)
- **Method:** Hook into Claude Code session output
- **Extracts:** Decisions made, code changes, project context updates

#### 5. Claude Conversations (raw archive)
- **Method:** Store every Claude interaction (this app's own AI calls + user's chat exports)
- **Purpose:** The most valuable long-term data source. As models improve, re-processing these conversations will yield better and better extractions.
- **Storage:** Full request/response pairs, timestamps, which model was used, which version of extraction prompts

### Ingestion Pipeline

```python
class IngestionPipeline:
    """Orchestrates all data source syncing."""

    def run_full_sync(self):
        """Initial onboarding — process all historical data."""
        # Gmail: paginate through all messages
        # Drive: paginate through all files
        # iMessage: read entire local DB
        # Deduplicate against existing records

    def run_incremental_sync(self):
        """Ongoing — only new/changed items since last cursor."""
        # Gmail: historyId delta
        # Drive: pageToken delta
        # iMessage: timestamp delta

    def process_email(self, message):
        """Single email through the full pipeline."""
        # 1. Classify (local LLM)
        # 2. Extract (Haiku or regex depending on classification)
        # 3. Resolve entities
        # 4. Store in PostgreSQL
        # 5. Update vector embeddings
        # 6. Regenerate affected markdown files
```

---

## Processing Pipeline

### Stage 1: Classification (Local LLM — $0)

**Model:** Qwen3 4B via Ollama (use /no_think mode for fast classification)
**Latency:** <100ms per item

Classify each email into one of:
- `HUMAN` — Real person writing specifically to recipient → route to deep analysis
- `AUTOMATED` — Receipts, shipping, confirmations, alerts → route to regex parse
- `NEWSLETTER` — Marketing, subscriptions → tag and archive
- `SPAM` — Unsolicited, cold outreach → skip
- `SYSTEM` — Password resets, 2FA, account notifications → skip

Also detect: urgency (urgent/normal/low), sender type (known/unknown/company).

**Output:**
```json
{
    "classification": "human",
    "confidence": 0.94,
    "urgency": "normal",
    "sender_type": "known",
    "route_to": "deep_analysis"
}
```

### Stage 2a: Deep Analysis (Claude Haiku — human emails only)

**Cost:** ~$0.0003 per email (~$0.03/month for 1000 emails)

Provide the model with known projects and people as context. Extract:

1. **Tasks** — Action items assigned to recipient
2. **Commitments** — Promises made ("I'll...", "I will...")
3. **Questions** — Unanswered questions
4. **Waiting On** — Things sender is waiting for
5. **Project Links** — Which known projects this relates to
6. **New Projects** — Any new projects mentioned
7. **People Mentioned** — Names referenced
8. **Sentiment** — Overall tone
9. **Reply Needed** — Boolean + urgency
10. **Suggested Reply** — Draft reply matching user's style with that person

**Output:**
```json
{
    "tasks": [{"text": "Send API docs", "assigned_to": "me", "deadline": null, "priority": "normal"}],
    "commitments": [{"text": "Review by Friday", "by": "sender", "deadline": "2026-02-07"}],
    "questions": [{"text": "Can you check the endpoint?", "answered": false}],
    "waiting_on": [{"text": "API docs", "from": "sarah-chen", "since": "2026-01-28"}],
    "project_links": ["trading-bot"],
    "new_projects": [],
    "people_mentioned": ["sarah-chen"],
    "sentiment": "neutral",
    "reply_needed": true,
    "reply_urgency": "normal",
    "suggested_reply": "Hey Sarah, I'll check the endpoint today and let you know."
}
```

### Stage 2b: Quick Parse (Regex — automated emails, $0)

Extract structured data with regex patterns:
- Order numbers, tracking numbers
- Dollar amounts, dates, statuses
- Carrier info (UPS, USPS, FedEx)

### Stage 3: Entity Resolution

After extraction:
- **People:** Fuzzy match on name/email against existing records
- **Projects:** Semantic similarity + keyword match against known projects
- Create new entities when no match found
- Deduplicate across sources (same person emailing and texting)

---

## Database Schema

### PostgreSQL (source of truth)

**Core entities:**

```sql
-- People you interact with
CREATE TABLE people (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name TEXT NOT NULL,
    email TEXT,
    phone TEXT,
    relationship TEXT CHECK (relationship IN
        ('colleague', 'advisor', 'friend', 'family', 'vendor', 'acquaintance', 'unknown')),
    organization TEXT,
    first_contact TIMESTAMP,
    last_contact TIMESTAMP,
    notes TEXT,
    metadata JSONB DEFAULT '{}',
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

-- Email accounts (multi-account support)
CREATE TABLE email_accounts (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name TEXT NOT NULL,             -- 'personal', 'school', 'work'
    email TEXT UNIQUE NOT NULL,
    provider TEXT DEFAULT 'gmail',
    priority_weight FLOAT DEFAULT 1.0,  -- multiplier for email priority scoring
    sync_enabled BOOLEAN DEFAULT TRUE,
    process_newsletters BOOLEAN DEFAULT FALSE,
    oauth_token JSONB,              -- encrypted token data
    sync_cursor TEXT,               -- historyId for Gmail
    last_sync TIMESTAMP,
    metadata JSONB DEFAULT '{}',
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

-- Projects (auto-tiered)
CREATE TABLE projects (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name TEXT NOT NULL,
    slug TEXT UNIQUE NOT NULL,
    tier TEXT CHECK (tier IN ('fleeting', 'simple', 'complex', 'life_thread')) DEFAULT 'simple',
    status TEXT CHECK (status IN ('active', 'paused', 'completed', 'abandoned')) DEFAULT 'active',
    description TEXT,
    first_mention TIMESTAMP,
    last_activity TIMESTAMP,
    mention_count INTEGER DEFAULT 0,
    source_diversity INTEGER DEFAULT 0,
    people_count INTEGER DEFAULT 0,
    -- User priority overrides (these always win over auto-scoring)
    user_pinned BOOLEAN DEFAULT FALSE,      -- manually pinned = always show prominently
    user_priority TEXT CHECK (user_priority IN ('critical', 'high', 'normal', 'low', NULL)),
    user_deadline DATE,                      -- user-set hard deadline
    user_deadline_note TEXT,                  -- e.g., "GRE exam date"
    auto_archive_after DATE,                 -- auto-demote after this date (for time-bounded things)
    metadata JSONB DEFAULT '{}',
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

-- Sprints (time-bounded priority overrides)
-- e.g., "GRE prep" from now until Feb 13 — boosts everything GRE-related
CREATE TABLE sprints (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name TEXT NOT NULL,                      -- "GRE Prep", "Job Search Sprint"
    description TEXT,
    project_id UUID REFERENCES projects(id) ON DELETE CASCADE,  -- which project this boosts
    priority_boost FLOAT DEFAULT 2.0,        -- multiplier applied during active period
    starts_at TIMESTAMP NOT NULL,
    ends_at TIMESTAMP NOT NULL,              -- after this, sprint auto-deactivates
    is_active BOOLEAN DEFAULT TRUE,
    auto_archive_project BOOLEAN DEFAULT TRUE,  -- demote linked project when focus ends
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX idx_sprints_active ON sprints(is_active) WHERE is_active = TRUE;
CREATE INDEX idx_sprints_dates ON sprints(starts_at, ends_at);

-- Tasks / Kanban items
CREATE TABLE tasks (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id UUID REFERENCES projects(id) ON DELETE SET NULL,
    title TEXT NOT NULL,
    description TEXT,
    status TEXT CHECK (status IN ('backlog', 'in_progress', 'waiting', 'done')) DEFAULT 'backlog',
    priority TEXT CHECK (priority IN ('urgent', 'high', 'normal', 'low')) DEFAULT 'normal',
    assigned_to UUID REFERENCES people(id) ON DELETE SET NULL,
    waiting_on UUID REFERENCES people(id) ON DELETE SET NULL,
    waiting_since TIMESTAMP,
    due_date DATE,
    -- User override fields
    user_pinned BOOLEAN DEFAULT FALSE,       -- manually pinned task
    user_priority TEXT CHECK (user_priority IN ('urgent', 'high', 'normal', 'low', NULL)),
    source_type TEXT,  -- 'email', 'text', 'drive', 'manual', 'user'
    source_id TEXT,
    source_account_id UUID REFERENCES email_accounts(id) ON DELETE SET NULL,
    created_at TIMESTAMP DEFAULT NOW(),
    completed_at TIMESTAMP,
    updated_at TIMESTAMP DEFAULT NOW()
);

-- Commitments (promises you or others made)
CREATE TABLE commitments (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    person_id UUID REFERENCES people(id) ON DELETE SET NULL,
    project_id UUID REFERENCES projects(id) ON DELETE SET NULL,
    direction TEXT CHECK (direction IN ('from_me', 'to_me')) NOT NULL,
    description TEXT NOT NULL,
    deadline DATE,
    status TEXT CHECK (status IN ('open', 'fulfilled', 'broken', 'cancelled')) DEFAULT 'open',
    source_type TEXT,
    source_id TEXT,
    created_at TIMESTAMP DEFAULT NOW(),
    fulfilled_at TIMESTAMP,
    updated_at TIMESTAMP DEFAULT NOW()
);

-- Processed emails
CREATE TABLE emails (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    account_id UUID REFERENCES email_accounts(id) ON DELETE SET NULL,  -- which account
    gmail_id TEXT NOT NULL,
    thread_id TEXT,
    sender_id UUID REFERENCES people(id) ON DELETE SET NULL,
    subject TEXT,
    snippet TEXT,
    full_body TEXT,
    classification TEXT CHECK (classification IN
        ('human', 'automated', 'newsletter', 'spam', 'system')),
    urgency TEXT CHECK (urgency IN ('urgent', 'normal', 'low')),
    needs_reply BOOLEAN DEFAULT FALSE,
    reply_suggested TEXT,
    reply_sent BOOLEAN DEFAULT FALSE,
    labels TEXT[],
    processed_at TIMESTAMP,
    email_date TIMESTAMP,
    raw_headers JSONB,
    extraction_result JSONB,
    created_at TIMESTAMP DEFAULT NOW(),
    UNIQUE(account_id, gmail_id)  -- unique per account, not globally
);

-- Text messages
CREATE TABLE messages (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    source_id TEXT UNIQUE NOT NULL,
    sender_id UUID REFERENCES people(id) ON DELETE SET NULL,
    content TEXT,
    is_from_me BOOLEAN,
    chat_id TEXT,
    message_date TIMESTAMP,
    has_attachment BOOLEAN DEFAULT FALSE,
    extraction_result JSONB,
    created_at TIMESTAMP DEFAULT NOW()
);

-- Google Drive documents
CREATE TABLE documents (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    drive_id TEXT UNIQUE NOT NULL,
    title TEXT,
    mime_type TEXT,
    folder_path TEXT,
    owner_id UUID REFERENCES people(id) ON DELETE SET NULL,
    last_modified TIMESTAMP,
    content_hash TEXT,
    extracted_text TEXT,
    linked_projects UUID[],
    metadata JSONB,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

-- Junction tables
CREATE TABLE project_people (
    project_id UUID REFERENCES projects(id) ON DELETE CASCADE,
    person_id UUID REFERENCES people(id) ON DELETE CASCADE,
    role TEXT,
    PRIMARY KEY (project_id, person_id)
);

-- Sync state (per source, per account)
CREATE TABLE sync_state (
    id TEXT PRIMARY KEY,  -- 'gmail:personal', 'gmail:school', 'drive', 'imessage'
    account_id UUID REFERENCES email_accounts(id) ON DELETE CASCADE,
    last_sync TIMESTAMP,
    cursor TEXT,
    status TEXT,
    error_message TEXT,
    updated_at TIMESTAMP DEFAULT NOW()
);

-- =====================================================
-- RAW INTERACTION ARCHIVE
-- =====================================================
-- This is the most valuable table in the system.
-- Store EVERY interaction verbatim. Extracted/structured data
-- is a view on top of this — disposable and re-generable.
-- As models improve, re-process raw data for better extractions.

-- Raw interactions — permanent archive of every data point
CREATE TABLE raw_interactions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    source_type TEXT NOT NULL,          -- 'email', 'text', 'drive', 'claude_conversation',
                                        -- 'claude_code_session', 'ai_extraction'
    source_id TEXT,                      -- external ID (gmail_id, message rowid, etc.)
    account_id UUID REFERENCES email_accounts(id) ON DELETE SET NULL,
    raw_content TEXT NOT NULL,           -- the actual content, verbatim
    raw_metadata JSONB DEFAULT '{}',     -- headers, timestamps, participants, etc.
    content_hash TEXT,                   -- for dedup
    -- Processing tracking
    extraction_version TEXT,             -- which version of prompts/models processed this
    extraction_model TEXT,               -- 'claude-haiku-4-5', 'qwen3:4b', etc.
    extraction_result JSONB,             -- what we extracted (can re-run later)
    last_processed_at TIMESTAMP,
    -- Timestamps
    interaction_date TIMESTAMP,          -- when the original interaction happened
    ingested_at TIMESTAMP DEFAULT NOW(), -- when we first stored it
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX idx_raw_source ON raw_interactions(source_type, source_id);
CREATE INDEX idx_raw_account ON raw_interactions(account_id);
CREATE INDEX idx_raw_date ON raw_interactions(interaction_date);
CREATE INDEX idx_raw_hash ON raw_interactions(content_hash);
CREATE INDEX idx_raw_extraction_version ON raw_interactions(extraction_version);

-- AI conversation archive — specifically for Claude interactions
-- (Both the system's own AI calls and user chat exports)
CREATE TABLE ai_conversations (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_type TEXT NOT NULL,          -- 'extraction', 'classification', 'user_chat',
                                         -- 'claude_code', 'draft_generation'
    model TEXT NOT NULL,                  -- 'claude-haiku-4-5', 'qwen3:4b'
    prompt_version TEXT,                  -- version tag for the prompt template used
    request_messages JSONB NOT NULL,      -- full message array sent to model
    response_content JSONB NOT NULL,      -- full response from model
    input_tokens INTEGER,
    output_tokens INTEGER,
    cost_usd FLOAT,                       -- track spend
    latency_ms INTEGER,
    -- Link to what triggered this
    source_interaction_id UUID REFERENCES raw_interactions(id) ON DELETE SET NULL,
    project_id UUID REFERENCES projects(id) ON DELETE SET NULL,
    metadata JSONB DEFAULT '{}',
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX idx_ai_conversations_type ON ai_conversations(session_type);
CREATE INDEX idx_ai_conversations_model ON ai_conversations(model);
CREATE INDEX idx_ai_conversations_date ON ai_conversations(created_at);

-- Audit log
CREATE TABLE audit_log (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    table_name TEXT NOT NULL,
    record_id UUID,
    action TEXT CHECK (action IN ('create', 'read', 'update', 'delete')) NOT NULL,
    actor TEXT NOT NULL,
    old_values JSONB,
    new_values JSONB,
    timestamp TIMESTAMP DEFAULT NOW()
);

-- User preferences
CREATE TABLE user_preferences (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    key TEXT UNIQUE NOT NULL,
    value JSONB NOT NULL,
    updated_at TIMESTAMP DEFAULT NOW()
);
```

**Indexes — add these:**
```sql
CREATE INDEX idx_people_email ON people(email);
CREATE INDEX idx_people_name ON people USING gin(to_tsvector('english', name));
CREATE INDEX idx_email_accounts_email ON email_accounts(email);
CREATE INDEX idx_projects_status ON projects(status);
CREATE INDEX idx_projects_tier ON projects(tier);
CREATE INDEX idx_projects_pinned ON projects(user_pinned) WHERE user_pinned = TRUE;
CREATE INDEX idx_projects_deadline ON projects(user_deadline) WHERE user_deadline IS NOT NULL;
CREATE INDEX idx_tasks_status ON tasks(status);
CREATE INDEX idx_tasks_project ON tasks(project_id);
CREATE INDEX idx_tasks_assigned ON tasks(assigned_to);
CREATE INDEX idx_tasks_pinned ON tasks(user_pinned) WHERE user_pinned = TRUE;
CREATE INDEX idx_tasks_due ON tasks(due_date) WHERE due_date IS NOT NULL;
CREATE INDEX idx_commitments_status ON commitments(status);
CREATE INDEX idx_commitments_direction ON commitments(direction);
CREATE INDEX idx_emails_classification ON emails(classification);
CREATE INDEX idx_emails_needs_reply ON emails(needs_reply) WHERE needs_reply = TRUE;
CREATE INDEX idx_emails_thread ON emails(thread_id);
CREATE INDEX idx_emails_account ON emails(account_id);
CREATE INDEX idx_messages_chat ON messages(chat_id);
CREATE INDEX idx_messages_date ON messages(message_date);
CREATE INDEX idx_documents_folder ON documents(folder_path);
CREATE INDEX idx_documents_title ON documents USING gin(to_tsvector('english', title));
CREATE INDEX idx_audit_timestamp ON audit_log(timestamp);
```

### Chroma (vector search)

Four collections, all using cosine similarity:
- `emails` — Email body embeddings
- `documents` — Drive document embeddings
- `projects` — Project description embeddings
- `raw_interactions` — All raw content (enables "search everything I've ever discussed")

---

## Project Tier System

Projects auto-tier based on activity signals, but **user overrides always win**:

```python
def calculate_project_tier(project):
    score = 0
    score += log(mention_count) * 2
    score += len(unique_sources) * 3       # email, drive, calendar, etc.
    score += len(people_involved) * 1.5
    score += months_active * 0.5
    score += len(attachments) * 0.3

    if score < 5:  return "fleeting"
    if score < 15: return "simple"
    if score < 40: return "complex"
    return "life_thread"
```

| Tier          | Signal                        | Output                                       |
|---------------|-------------------------------|----------------------------------------------|
| **Fleeting**  | Single mention, no follow-up  | Tag or bullet in `Interests.md`              |
| **Simple**    | Few refs over weeks           | Single `ProjectName.md`                      |
| **Complex**   | Many refs, people, sub-tasks  | Folder: README, KANBAN, PEOPLE, DECISIONS    |
| **Life Thread**| Years of context             | Domain folder: Philosophy, History, Tools    |

Projects level up when activity increases, level down when stale.

---

## User Priority System

The auto-organization is the baseline. User intent is the override layer. This section defines how the two combine.

### Effective Priority Calculation

Every project and task has an **effective priority** that blends three signals:

```python
def effective_priority(item, now=datetime.now()):
    """
    Combine user intent, temporal urgency, and AI-inferred importance.
    User overrides always dominate.
    """
    score = 0.0

    # 1. USER OVERRIDE (highest weight — if user says it matters, it matters)
    if item.user_pinned:
        score += 100
    if item.user_priority:
        score += {'critical': 80, 'high': 40, 'normal': 0, 'low': -20}[item.user_priority]

    # 2. TEMPORAL URGENCY (deadline proximity creates exponential urgency)
    deadline = item.user_deadline or item.due_date
    if deadline:
        days_left = (deadline - now.date()).days
        if days_left <= 0:
            score += 90    # Overdue
        elif days_left <= 3:
            score += 70    # This week, imminent
        elif days_left <= 7:
            score += 40    # This week
        elif days_left <= 14:
            score += 20    # Next two weeks
        # else: deadline exists but far away, minor boost
        else:
            score += 5

    # 3. ACTIVE SPRINT BOOST
    active_sprint = get_active_sprint_for(item.project_id, now)
    if active_sprint:
        score *= active_sprint.priority_boost  # e.g., 2.0x during "GRE Prep"

    # 4. ACCOUNT WEIGHT (work emails > personal for priority)
    if item.source_account_id:
        account = get_account(item.source_account_id)
        score *= account.priority_weight

    # 5. AI-INFERRED IMPORTANCE (lowest weight — the baseline)
    score += item.ai_urgency_score or 0  # from extraction pipeline

    return score
```

### Focus Modes

Time-bounded priority overrides for things like exam prep, job searches, or project sprints.

```bash
# CLI examples
focus sprint create "GRE Prep" --project gre-study --until 2026-02-13 --boost 2.0
focus sprint create "Job Search Sprint" --project job-search --until 2026-03-01
focus sprint list
focus sprint deactivate "GRE Prep"
```

When a sprint is active:
- The linked project and all its tasks get a priority multiplier
- Daily notes highlight sprint items first
- CLAUDE.md mentions the active sprint
- Email extraction is primed to flag anything related

When a sprint expires:
- If `auto_archive_project` is true, the project gets demoted (status → completed or paused)
- Tasks under it get moved to done or archived
- A summary is generated: "GRE Prep focus ended. Here's what you accomplished."

**Example: GRE on Feb 13th**

```
sprint:
  name: "GRE Prep"
  project: gre-study
  starts_at: 2026-02-05
  ends_at: 2026-02-13
  priority_boost: 2.0
  auto_archive_project: true

Effect:
  - Feb 5-13: Everything GRE-related bubbles to the top
  - Daily notes lead with GRE tasks
  - CLAUDE.md says "ACTIVE SPRINT: GRE exam Feb 13"
  - Feb 14: Auto-archive. GRE project → completed. Summary generated.
```

### User Override CLI

```bash
# Pin a project (always show prominently)
focus project pin "trading-bot"
focus project unpin "trading-bot"

# Set priority manually
focus project priority "nyu-application" critical
focus task priority "send-transcript" urgent

# Set deadlines
focus project deadline "nyu-application" 2026-03-01 --note "Application due"
focus task deadline "send-transcript" 2026-02-20

# Create a task manually (not extracted from email)
focus task create "Study GRE vocab chapter 7" --project gre-study --due 2026-02-10

# View priorities
focus priorities           # Show effective priority ranking
focus priorities --week    # What matters this week
focus priorities --today   # What matters today
```

### Priority in Generated Output

The vault's daily note and inbox views respect effective priority. Sprint items appear first, then deadlines, then pinned projects, then inbox sorted by effective priority with account labels. See the Daily Note example in the Output File System section for the full template.

---

## Output File System

### Design Principle: Each File Has One Job

The vault is a hierarchy of files where information flows **downward** (broad → specific) and references flow **upward** (specific files link back to parents). No file duplicates another — each one owns its data and other files point to it.

```
CLAUDE.md (Claude Code reads this — the briefing)
    ↓ references
vault/ (humans browse this — the knowledge base)
    ↓ contains
    Per-project files (README, KANBAN, PEOPLE, DECISIONS, EMAILS)
    Per-person files
    Inbox views
    Daily notes
```

**CLAUDE.md** is NOT inside the vault. It lives at the project root (where Claude Code runs) and is optimized for machines. The vault is optimized for humans reading in Obsidian.

### File Ownership Map

| File | Owner of | Read by | Written by |
|------|----------|---------|------------|
| `CLAUDE.md` | Current project context for Claude Code | Claude Code | Focus generator |
| `vault/Projects/X/README.md` | Project overview, description, links | Humans (Obsidian) | Generator |
| `vault/Projects/X/KANBAN.md` | Task status, backlog, blockers | Humans + CLAUDE.md pulls from | Generator |
| `vault/Projects/X/PEOPLE.md` | Who's involved, roles, contact info | Humans + CLAUDE.md pulls from | Generator |
| `vault/Projects/X/DECISIONS.md` | Key decisions and rationale | Humans + CLAUDE.md pulls from | Generator |
| `vault/Projects/X/EMAILS.md` | Email thread summaries for project | Humans | Generator |
| `vault/Projects/X/TIMELINE.md` | Chronological project history | Humans | Generator |
| `vault/People/X.md` | Everything about one person | Humans | Generator |
| `vault/Inbox/*.md` | Email triage views | Humans | Generator |
| `vault/Daily/DATE.md` | Daily briefing with priorities | Humans | Generator |
| `vault/Me/Preferences.md` | User coding style, conventions | CLAUDE.md pulls from | User + Generator |
| `vault/Me/Commitments.md` | Open promises in/out | Humans | Generator |

### Vault Directory Structure

```
project-root/
├── CLAUDE.md                         # Machine-readable project briefing
│                                     # (at project root, NOT inside vault)
│
└── vault/
    ├── Domains/                      # Life Threads (years of context)
    │   ├── Trading/
    │   │   ├── README.md             # Domain overview
    │   │   ├── Philosophy.md         # Trading philosophy, principles
    │   │   ├── Current-Positions.md  # Live positions
    │   │   ├── Theses/
    │   │   │   ├── Semiconductor-Supply-Chain.md
    │   │   │   └── Memory-Stocks.md
    │   │   └── Tools/
    │   │       └── Bot-Architecture.md
    │   └── Japanese-Learning/
    │       ├── README.md
    │       └── Progress.md
    │
    ├── Projects/                     # Active Complex projects
    │   ├── Focus/
    │   │   ├── README.md             # What is this, overview, related
    │   │   ├── KANBAN.md             # Tasks: backlog, in-progress, waiting, done
    │   │   ├── PEOPLE.md             # Collaborators, roles, contact, status
    │   │   ├── DECISIONS.md          # What was decided, why, when, by whom
    │   │   ├── EMAILS.md             # Relevant email thread summaries
    │   │   └── TIMELINE.md           # Chronological activity log
    │   ├── Color-Perception-Paper/
    │   │   ├── README.md
    │   │   ├── KANBAN.md
    │   │   ├── PEOPLE.md
    │   │   ├── DECISIONS.md
    │   │   └── EMAILS.md
    │   └── NYU-Application/
    │       └── README.md
    │
    ├── SimpleProjects/               # Simple tier (one file each)
    │   ├── Japan-Trip-Planning.md
    │   └── Home-Office-Setup.md
    │
    ├── People/                       # One file per person
    │   ├── Prof-Zed-Adams.md
    │   ├── Sarah-Chen.md
    │   └── ...
    │
    ├── Inbox/                        # Email triage (for humans)
    │   ├── NeedsReply/
    │   │   ├── urgent.md
    │   │   └── normal.md
    │   ├── Waiting/
    │   │   └── waiting-on-others.md
    │   ├── FYI/
    │   │   └── informational.md
    │   ├── Automated/
    │   │   ├── orders.md
    │   │   ├── bills.md
    │   │   └── alerts.md
    │   └── EMAIL-DRAFTS.md
    │
    ├── Me/                           # User's own info
    │   ├── Preferences.md            # Coding style, conventions, tools
    │   ├── Current-Goals.md          # High-level goals
    │   └── Commitments.md            # Promises made to/by others
    │
    └── Daily/                        # Daily briefings
        └── 2026-02-05.md
```

---

## CLAUDE.md Specification

CLAUDE.md is the **single file Claude Code reads to understand the project**. It is not a summary — it's a specialized briefing document that inlines exactly what Claude Code needs to be productive, formatted for machine consumption.

### Placement

CLAUDE.md lives at the **root of the code project**, not inside the vault:

```
~/focus/
├── CLAUDE.md          ← Claude Code reads this
├── src/
├── tests/
├── vault/             ← Humans browse this in Obsidian
│   └── Projects/
│       └── Focus/
│           ├── README.md
│           ├── KANBAN.md
│           └── ...
└── ...
```

If the user has multiple code projects, each one gets its own CLAUDE.md pointing into the shared vault.

### What Goes IN CLAUDE.md (inlined, not referenced)

These are things Claude Code needs immediately, every session, without having to read other files:

1. **Project identity** — What this is, in one paragraph
2. **Architecture snapshot** — Tech stack, key patterns, directory layout
3. **Current sprint** — The 3-5 things that matter RIGHT NOW (pulled from KANBAN.md's in-progress + waiting)
4. **Active blockers** — What's stuck and on whom (pulled from KANBAN.md's waiting section)
5. **Active sprint** — If there's a time-bounded priority, state it plainly
6. **Coding conventions** — The user's style rules (pulled from Me/Preferences.md)
7. **Key decisions** — Recent decisions that affect how to write code (pulled from DECISIONS.md, last 5-10)
8. **People context** — Who's involved, what they're doing, what we're waiting on (pulled from PEOPLE.md, active only)

### What Goes OUT of CLAUDE.md (referenced via path)

These are things Claude Code might need occasionally but shouldn't clutter the briefing:

- Full project history → `vault/Projects/X/TIMELINE.md`
- Complete task backlog → `vault/Projects/X/KANBAN.md`
- All decisions ever → `vault/Projects/X/DECISIONS.md`
- Email thread details → `vault/Projects/X/EMAILS.md`
- Person deep-dives → `vault/People/Person-Name.md`
- User goals and commitments → `vault/Me/`

### CLAUDE.md Template

```markdown
# CLAUDE.md — Focus

> Auto-generated by Focus. Last updated: 2026-02-05T14:30:00Z
> Source: vault/Projects/Focus/

## Project

Local-first AI-powered PKM system. Ingests email/texts/docs, extracts
structured data via tiered LLM pipeline, generates self-organizing
Obsidian vault. Python 3.11 + FastAPI + PostgreSQL + Chroma + Ollama.

## Architecture

```
src/
├── ingestion/      # Gmail, Drive, iMessage connectors
│   ├── gmail.py    # OAuth + incremental sync via historyId
│   ├── drive.py    # Changes API sync
│   └── imessage.py # SQLite reader (macOS)
├── processing/     # Tiered AI pipeline
│   ├── classifier.py   # Ollama + Qwen3 4B (local, $0)
│   ├── extractor.py    # Claude Haiku (tasks, commitments, people)
│   └── resolver.py     # Entity resolution + project linking
├── storage/        # Data layer
│   ├── db.py       # PostgreSQL via SQLAlchemy
│   ├── vectors.py  # Chroma embeddings
│   └── raw.py      # Raw interaction archive
├── output/         # Markdown generation
│   ├── vault.py    # Obsidian vault generator
│   ├── kanban.py   # Per-project kanban
│   └── claude_md.py # This file's generator
├── api/            # FastAPI REST endpoints
└── cli/            # Typer CLI (focus command)
```

Key patterns: async throughout, SQLAlchemy 2.0 style, Pydantic models
for all data, raw interactions stored permanently for reprocessing.

## Current Sprint

IN PROGRESS:
- Gmail OAuth + incremental email fetching (src/ingestion/gmail.py)
- Local LLM classifier via Ollama (src/processing/classifier.py)
- PostgreSQL schema + migrations (alembic/)

WAITING:
- Google OAuth app approval — submitted Jan 30, typically 3-5 days

UP NEXT:
- Claude Haiku extraction pipeline
- Basic markdown vault generation

## Blockers

- Google OAuth app in review — can use test mode (100 users) meanwhile
- Ollama Qwen3 4B sometimes misclassifies newsletter-style personal
  emails — need to tune classification prompt

## Active Sprint

NONE (or: "GRE Prep until Feb 13 — deprioritize non-essential work")

## Conventions

- Type hints on all functions
- Explicit over implicit
- Functions under 50 lines
- Docstrings on public functions (Google style)
- Tests for new features (pytest, async)
- snake_case everywhere
- Use `rich` for CLI output
- Use `loguru` or stdlib logging, not print()
- Prefer composition over inheritance
- Raw SQL only in migrations; use SQLAlchemy ORM elsewhere

## Recent Decisions

1. **Hybrid storage** (Feb 2): PostgreSQL is source of truth, markdown
   is generated output. DB → markdown, never the reverse.
2. **Tiered processing** (Feb 2): Local LLM for classification ($0),
   Haiku for extraction (~$0.0003/email). Sonnet only for ambiguous.
3. **Raw storage** (Feb 5): Store all raw interactions permanently.
   Extracted data is disposable; raw data is the real asset.
4. **Multi-account email** (Feb 5): email_accounts table with
   per-account OAuth and priority weights.
5. **Sprints** (Feb 5): Time-bounded priority boosts with
   auto-archive on expiry.

## People

- **Nathan** (owner) — building this solo for now
- **Sarah Chen** (future collaborator) — may help with API integration
  WAITING: API docs from her (7 days overdue)

## Deep Context (read these files if you need more)

- Full task backlog: vault/Projects/Focus/KANBAN.md
- All decisions: vault/Projects/Focus/DECISIONS.md
- Project history: vault/Projects/Focus/TIMELINE.md
- Email threads: vault/Projects/Focus/EMAILS.md
- User preferences: vault/Me/Preferences.md
- User commitments: vault/Me/Commitments.md
```

### How CLAUDE.md Stays Current

The generator pulls from the database, not from other markdown files. The flow is:

```
PostgreSQL (source of truth)
    ↓
Generator queries DB for:
    - project metadata
    - tasks WHERE status IN ('in_progress', 'waiting') AND project = X
    - decisions ORDER BY created_at DESC LIMIT 10
    - people WHERE project = X AND active
    - sprints WHERE is_active = TRUE
    - user_preferences WHERE key LIKE 'coding.%'
    ↓
Writes CLAUDE.md (at project root)
    AND
Writes vault/Projects/X/*.md files (in vault)
```

Both outputs come from the same DB queries. CLAUDE.md gets the condensed machine version. Vault files get the expanded human version. They never go out of sync because they share the same source.

### Regeneration Triggers

CLAUDE.md regenerates when:
- `focus sync` pulls new data that affects this project
- `focus generate` is run manually
- A sprint starts or expires
- User changes a project priority or deadline
- The daemon detects changes (every N minutes)

It does NOT regenerate mid-session — Claude Code reads it once at session start and works from that snapshot.

---

## Vault File Examples

### Project README.md (human-facing overview)

```markdown
# Trading Bot
> AI-powered algorithmic trading system for options

**Status**: Active | **Tier**: Life Thread
**First Started**: 2024-03-15 | **Last Activity**: 2026-02-01

## Overview
Multi-model trading bot using Claude and GPT-4 for options analysis.

## Current Focus
- Implementing stop-loss logic
- Researching Tastytrade API integration

## Quick Links
- [[KANBAN]] — Task board
- [[PEOPLE]] — Who's involved
- [[DECISIONS]] — Key choices made
- [[EMAILS]] — Related email threads
- [[TIMELINE]] — Project history

## Related
- [[Semiconductor Supply Chain Thesis]]
- [[Schwab API Integration]]
```

### KANBAN.md (task board — single source of truth for task status)

```markdown
# Tasks: Trading Bot

## Backlog
- [ ] Add support for options spreads #feature
- [ ] Research Tastytrade API #research

## In Progress
- [ ] Fix position sizing bug #bug @nathan — Started: 2026-01-30
- [ ] Implement stop-loss logic #feature @nathan — Started: 2026-02-01

## Waiting On
- [ ] API documentation from Sarah #blocked @sarah
      Source: Email 2026-01-28 | Days waiting: 5 | **Suggested**: Follow up

## Done (This Week)
- [x] Basic order execution — done 2026-01-15
- [x] Schwab OAuth integration — done 2026-01-20
```

### PEOPLE.md (who's involved in this project)

```markdown
# People: Trading Bot

## Active

### Nathan (Owner)
Primary developer. Working on stop-loss logic and position sizing.

### Sarah Chen (API Integration)
**Email**: sarah@example.com | **Org**: TechCorp
**Status**: Waiting on API docs (5 days)
**Style**: Prefers Slack, very responsive, casual tone
→ Full profile: [[Sarah Chen]]

## Past Contributors
(none yet)
```

### DECISIONS.md (why things are the way they are)

```markdown
# Decisions: Trading Bot

## 2026-02-01 — Use Schwab API over Tastytrade
**Context**: Needed a broker API for execution.
**Decision**: Go with Schwab — better docs, Nathan already has account.
**Trade-off**: Tastytrade has better options support, may revisit.
**Source**: Email thread with Sarah, Jan 25-28

## 2026-01-15 — Multi-model architecture
**Context**: Single model wasn't reliable enough for trade signals.
**Decision**: Use Claude for analysis, GPT-4 for confirmation, majority vote.
**Trade-off**: Higher latency, higher cost, but significantly fewer bad trades.
```

### Person file (vault/People/Sarah-Chen.md)

```markdown
# Sarah Chen
**Email**: sarah@example.com | **Relationship**: Colleague | **Org**: TechCorp

## Current Context
- Working on: [[Trading Bot]] (API integration)
- **Waiting on her**: API documentation (5 days overdue)
- **Open threads**: 1

## Interaction History
First Contact: 2025-06-15 | Last Contact: 2026-01-28 | Total: 47 interactions

## Notes
Technical lead, very responsive. Prefers Slack over email.
Casual tone works best. Quick to help when not overloaded.

## Recent Threads
- 2026-01-28: Re: API Integration — asked for docs
- 2026-01-25: Re: API Integration — initial discussion
```

### EMAIL-DRAFTS.md (suggested replies for humans)

```markdown
# Suggested Emails

## High Priority

### Follow up: Sarah Chen — API Documentation
**Why**: Asked for docs Jan 28, no response in 5 days. Blocking [[Trading Bot]].
**Your style with Sarah**: casual, direct

> Hey! Just bumping this — any luck finding those API docs?
> No rush if you're slammed, just trying to plan my week.

[Open Gmail](link) | [sent] | [edit] | [snooze] 3d | x Dismiss
```

### Daily Note (vault/Daily/2026-02-08.md)

```markdown
# 2026-02-08

## Active Sprint: GRE Prep (5 days left)
- [ ] Practice quantitative section (30 min)
- [ ] Review vocabulary chapters 6-8
- [ ] Take practice test #3

## Due This Week
- [ ] NYU application supplemental essay — due Feb 10
- [ ] Send transcript request — due Feb 10

## Pinned Projects
- [[Trading Bot]] — waiting on API docs from Sarah (7 days)
- [[Focus]] — Week 1 build in progress

## Needs Reply (by priority)
- [school] Prof Adams — Paper feedback (3 days, HIGH)
- [work] Manager — Sprint planning (1 day, NORMAL)
- [personal] Mom — Weekend plans (5 days, LOW)

## Completed Today
(auto-populated as tasks are marked done)
```

---

## CLI Interface

```bash
# Setup & sync
focus init              # First-time setup wizard
focus account add       # Add a new email account (OAuth flow)
focus sync              # Pull new data from all sources
focus sync --account personal   # Sync specific account
focus generate          # Regenerate all markdown outputs
focus daemon            # Run continuously (sync + generate on interval)
focus status            # Show sync state, counts, errors

# Priority & focus
focus priorities                # Show effective priority ranking
focus priorities --week         # What matters this week
focus priorities --today        # What matters right now
focus sprint create "Name" --project slug --until DATE --boost 2.0
focus sprint list                # Show active sprints
focus sprint deactivate "Name"   # End a sprint early

# Projects & tasks
focus project pin "slug"        # Pin a project
focus project priority "slug" critical
focus project deadline "slug" 2026-03-01 --note "Why"
focus task create "Title" --project slug --due DATE
focus task priority "task-id" urgent

# Search & data
focus search "query"            # Semantic search across all data
focus reprocess --since 2025-01-01  # Re-extract raw data with current models
```

---

## Configuration

Store in `~/.config/focus/config.toml`:

```toml
[general]
vault_path = "~/Focus-Vault"
db_url = "postgresql://localhost/focus"
chroma_path = "~/.local/share/focus/chroma"
log_level = "INFO"

[anthropic]
api_key = ""    # Or read from env: ANTHROPIC_API_KEY
model = "claude-haiku-4-5-20251001"

[ollama]
model = "qwen3:4b"
base_url = "http://localhost:11434"

[sync]
interval_minutes = 15
imessage_enabled = false    # macOS only

[vault]
auto_regenerate = true
daily_notes = true

[raw_storage]
enabled = true                           # Store every raw interaction
store_ai_conversations = true            # Log all AI API calls
retention_days = -1                      # -1 = forever (recommended)
reprocess_on_model_upgrade = false       # Auto re-extract when models change
```

Email accounts are stored in the database (see `email_accounts` table) and managed via CLI:

```bash
focus account add       # Interactive OAuth flow
focus account list      # Show configured accounts
focus account priority "work" 2.0    # Set priority weight
focus account disable "newsletter-account"
```

---

## Build Order

1. **Gmail → PostgreSQL** — OAuth, fetch, store raw emails
2. **Classification** — Ollama integration, route emails
3. **Extraction** — Anthropic API, extract structured data from human emails
4. **Basic vault generation** — Markdown files from DB data
5. **Entity resolution** — People/project linking, dedup
6. **Inbox views** — NeedsReply, Waiting, Automated
7. **Email drafts** — Suggested replies queue
8. **Kanban generation** — Per-project task boards
9. **Google Drive** — Ingest docs, link to projects
10. **CLAUDE.md generation** — Project context files
11. **iMessage** (if on macOS)
12. **Daemon mode** — Continuous background sync
13. **Polish** — Error handling, performance, edge cases

---

## Success Criteria

- [ ] 10 minutes from OAuth to populated vault
- [ ] >90% email classification accuracy
- [ ] >80% task extraction accuracy
- [ ] <$5/month API costs for typical usage
- [ ] Claude Code can answer "what am I working on?" from CLAUDE.md
- [ ] Vault updates automatically as new data arrives

---

## Raw Data Philosophy

The most valuable thing Focus stores isn't the extracted tasks or the generated markdown — it's the raw interactions themselves.

### Why Store Everything Raw

Today's extraction pipeline uses Haiku for human emails and regex for automated ones. That's good enough for now. But in 6 months, the models will be better. In a year, dramatically so. If all you have is the extracted JSON, you're locked into today's quality. If you have the raw data, you can always re-extract.

**What gets stored in `raw_interactions`:**
- Every email body (verbatim)
- Every text message
- Every Google Doc snapshot
- Every Claude conversation (including the AI's own extraction calls)
- Every Claude Code session transcript

**What gets stored in `ai_conversations`:**
- Full request/response pairs for every AI call the system makes
- Which model and prompt version was used
- Token counts and costs
- Links back to the source interaction

### Re-Processing Pipeline

When models improve or extraction prompts are updated:

```bash
# Re-process all raw interactions from the last year with current models
focus reprocess --since 2025-01-01

# Re-process only emails that were extracted with an old prompt version
focus reprocess --extraction-version "v0.1"

# Dry run — show what would change without writing
focus reprocess --since 2025-01-01 --dry-run
```

The reprocess command:
1. Reads raw content from `raw_interactions`
2. Runs current extraction pipeline (classification + extraction)
3. Compares new results with old `extraction_result`
4. Updates structured tables (tasks, commitments, projects) with diffs
5. Logs the new extraction in `ai_conversations` with updated version tag
6. Regenerates affected markdown files

**Cost note:** Re-processing 10,000 emails through Haiku costs roughly $3. Cheap enough to do whenever there's a meaningful model upgrade.

### Storage Costs

Raw text is tiny. A year of email (5,000 emails averaging 2KB each) is ~10MB. A year of Claude conversations is maybe 50MB. Even 10 years of everything fits comfortably in a single PostgreSQL instance. The storage cost is negligible compared to the long-term value.

---

## HIPAA Note (Future)

For healthcare/enterprise use later, swap Anthropic API for AWS Bedrock:
- Claude runs in your VPC, data never leaves your AWS account
- AWS signs BAA (free, in console)
- Same code, different client initialization

Not needed for personal use — just use the Anthropic API directly.

---

## Environment

- **Dev machine:** Arch Linux (EndeavourOS)
- **Remote access:** Tailscale + SSH + tmux + RustDesk (self-hosted remote desktop)
- **User has:** Anthropic API key, Google OAuth credentials
- **Local services:** PostgreSQL, Ollama, Redis

---

*Version: 1.1.0 | Updated: 2026-02-05*
*v1.1: Swapped Llama 3.2 1B → Qwen3 4B for classification (better accuracy at same latency target). Added RustDesk for self-hosted remote desktop alongside Tailscale + SSH.*
*v1.0: Renamed from Knowledge OS → Focus. Added feature registry (19 features). Renamed focus modes → sprints to avoid CLI collision.*

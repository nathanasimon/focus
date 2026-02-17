# Focus Context System — Research & Implementation Brief

> Compiled 2026-02-09. For a future agent to implement.

## Vision

Focus becomes a **universal repository for all human information** — emails, documents, and critically, **all LLM conversations**. The system automatically records every agent interaction in the background, and automatically retrieves relevant context before the agent responds. The user never has to ask the agent to search; the system does it.

This combines ideas from three sources:
- **OneContext/Aline** — automatic conversation recording via Claude Code hooks
- **Git-Context-Controller (GCC)** — structured, multi-level agent memory (paper: arXiv:2508.00031)
- **Focus** — tiered AI classification pipeline + unified information store

---

## Part 1: Research Findings

### 1.1 OneContext / Aline

**What it is**: A conversation history tracking and retrieval system for AI agents. npm package `onecontext-ai` wraps Python package `aline-ai` (internal module name: `realign`).

**Architecture**: Two background daemons:
- **Watcher**: Detects when Claude Code finishes a turn (via hooks or polling). Enqueues jobs in SQLite.
- **Worker**: Claims jobs, parses raw JSONL transcripts, calls cloud LLM for title+summary per turn, stores in SQLite.

**Recording pipeline**:
1. Claude Code `Stop` hook fires after every response
2. Hook enqueues `session_process` job into `~/.aline/db/aline.db` (SQLite)
3. Worker reads the Claude Code JSONL transcript from `~/.claude/projects/<encoded-path>/*.jsonl`
4. Parses JSONL into turns by tracing `parentUUID` chains
5. Content-hashes each turn (MD5) for deduplication
6. Calls cloud LLM proxy (`realign-server.vercel.app`) for title + summary per turn
7. Stores: session record → turn records → turn_content (raw JSONL) in SQLite

**Storage schema** (SQLite, `~/.aline/db/aline.db`):
- `sessions` — one row per agent session (file path, workspace, timestamps, LLM summary)
- `turns` — individual conversation turns (user_message, assistant_summary, content_hash, llm_title, llm_description)
- `turn_content` — raw JSONL text, separated for performance
- `events` — higher-level groupings of sessions (many-to-many via `event_sessions`)
- `agents` — terminal-to-session mappings
- `agent_info` — agent identity/profile with name, title, description
- `agent_contexts` — context definitions for search scoping
- `jobs` — durable job queue with lease-based locking, exponential backoff

**Hierarchical summarization**: Turn → Session → Event → Agent. Each level LLM-generated, aggregating below.

**Context retrieval**: Agent invokes `/onecontext` skill → reads `~/.claude/skills/onecontext/SKILL.md` → taught to run `aline search` via Bash tool → searches SQLite. "Broad to Deep" pattern: Event → Session → Turn → Content.

**Context injection** (how it gets context into new sessions):
- Injects a block into `~/.claude/CLAUDE.md` telling the agent to proactively search history
- The agent decides when to invoke `/onecontext` skill based on those instructions
- The skill teaches the agent to run `aline search "pattern"` via Bash
- **This is agent-driven, not system-driven** — the agent must decide to search

**Context loading** (`aline context load`):
- Saves session/event IDs as a search filter
- Subsequent `aline search` calls return only results from loaded context
- Does NOT inject anything directly — just scopes search results

**Sharing**: AES encrypts turn content → uploads to Vercel API → returns shareable URL. Import reconstructs session/turn tree locally. Bidirectional sync via optimistic locking.

**Key design patterns**:
- Local-first SQLite (no external DB dependency)
- Hook-driven with polling fallback
- Content-hash deduplication (idempotent reprocessing)
- Watcher/Worker split (detection never blocks on LLM calls)
- Adapter pattern for Claude/Codex/Gemini
- Atomic file writes (`.tmp` + rename)
- Secret redaction via `detect-secrets`

**Limitations**:
- Agent-driven retrieval (agent must decide to search)
- Cloud LLM proxy required for summarization (no local option in current version)
- Only records agent conversations, not emails/docs/other sources
- No automatic context injection — relies on CLAUDE.md instruction + agent judgment

### 1.2 Git-Context-Controller (GCC)

**Paper**: "Git Context Controller: Manage the Context of LLM-based Agents like Git" (arXiv:2508.00031v1, Junde Wu, Oxford)

**What it is**: A structured context management framework that treats agent memory as a version-controlled file system. The agent calls explicit commands (COMMIT, BRANCH, MERGE, CONTEXT) to manage its own memory.

**File system structure**:
```
.GCC/
├── main.md              # Global roadmap, milestones, shared across all branches
├── branches/
│   └── <branch-name>/
│       ├── commit.md    # Milestone summaries (coarse-grained)
│       ├── log.md       # Every OTA (Observation-Thought-Action) cycle (fine-grained)
│       └── metadata.yaml # Architecture, deps, file structure
```

**Commands** (agent-callable, taught via system prompt):
- `COMMIT <summary>` — Checkpoint a milestone. Updates commit.md with: branch purpose, previous progress summary (rolling), this commit's contribution. Also creates a real git commit.
- `BRANCH <name>` — Create isolated workspace for exploring alternative approaches. New log.md + commit.md initialized.
- `MERGE <branch>` — Synthesize branch results back into main. Updates main.md with outcome, merges commit.md entries, merges log.md with origin tags.
- `CONTEXT <options>` — Multi-level retrieval:
  - No args: `git status`-style overview (main.md purpose + branch list)
  - `--branch <name>`: Branch purpose + last 10 commits (scrollable)
  - `--commit <hash>`: Full commit.md entry
  - `--log`: Last 20 lines of log.md (scrollable)
  - `--metadata <segment>`: Specific metadata.yaml section (file_structure, env_config)

**Key findings from paper**:
- 48.00% on SWE-Bench-Lite (SOTA, outperforming 26 systems)
- Self-replication case study: agent with GCC reproduces a CLI that scores 40.7% vs 11.7% without GCC
- Agents spontaneously developed disciplined behaviors (test-before-commit, branching to explore alternatives) from the memory structure alone
- The agent used BRANCH to prototype a RAG-based memory system, empirically compared it to the summary-based system, and abandoned RAG when it underperformed — all without being prompted

**Key insight**: The multi-level retrieval (main.md → branch → commit → log) lets agents zoom from high-level roadmap to fine-grained execution trace. This is the same "Broad to Deep" pattern OneContext uses, but structured as files rather than database queries.

**Limitations**:
- Agent-driven (agent must call COMMIT/BRANCH/CONTEXT)
- Single-agent focused (no multi-agent context sharing)
- Only tracks agent reasoning, not external information sources
- Requires system prompt space for command instructions

### 1.3 Claude Code Hooks System

**Available hooks** (14 total):

| Hook | When | Can block? | `additionalContext`? |
|------|------|-----------|---------------------|
| SessionStart | New/resumed session | No | Yes |
| **UserPromptSubmit** | User submits prompt, before processing | Yes | **Yes** |
| PreToolUse | Before tool executes | Yes | Yes (v2.1.19+) |
| PermissionRequest | Permission dialog appears | Yes | No |
| PostToolUse | After tool succeeds | No | Yes |
| PostToolUseFailure | After tool fails | No | Yes |
| Notification | Notification sent | No | Yes |
| SubagentStart | Subagent spawned | No | Yes |
| SubagentStop | Subagent finishes | Yes | No |
| **Stop** | Agent finishes responding | Yes | No |
| TeammateIdle | Team member about to idle | Yes | No |
| TaskCompleted | Task marked complete | Yes | No |
| PreCompact | Before context compaction | No | No |
| SessionEnd | Session ends | No | No |

**Input** (JSON on stdin, all hooks):
```json
{
  "session_id": "abc123",
  "transcript_path": "/path/to/transcript.jsonl",
  "cwd": "/current/working/directory",
  "permission_mode": "default",
  "hook_event_name": "UserPromptSubmit"
}
```
Event-specific fields: `prompt` (UserPromptSubmit), `tool_name`+`tool_input` (PreToolUse/PostToolUse), `source` (SessionStart), `stop_hook_active` (Stop).

**Context injection mechanism** — return JSON on stdout with exit 0:
```json
{
  "hookSpecificOutput": {
    "hookEventName": "UserPromptSubmit",
    "additionalContext": "This text is added to Claude's visible context"
  }
}
```

**What hooks CAN do**:
- Add text to Claude's context via `additionalContext` (UserPromptSubmit, SessionStart, PreToolUse, PostToolUse, SubagentStart, Notification)
- Block prompts (`decision: "block"` on UserPromptSubmit)
- Block/allow/modify tool calls (`permissionDecision` + `updatedInput` on PreToolUse)
- Force Claude to continue instead of stopping (`decision: "block"` on Stop)
- Show warnings to user (`systemMessage` field)

**What hooks CANNOT do**:
- Cannot modify the user's prompt text (only add alongside it)
- Cannot inject system-level instructions that override CLAUDE.md
- Cannot modify Claude's response after generation
- Cannot persist across sessions (must read/write files for persistence)

**Reliability notes**:
- Use JSON `additionalContext`, NOT plain stdout (plain stdout has had bugs — GitHub #13912)
- Use settings.json hooks, NOT plugin hooks (plugin hooks have open bug where output is silently discarded — GitHub #12151)
- `additionalContext` duplication bug was fixed in v2.1 (GitHub #14281)
- Hook timeout: 10 minutes default (600 seconds)

**Critical hooks for Focus**:
1. **UserPromptSubmit** — fires before Claude responds. Read the prompt, classify it, retrieve relevant context, return via `additionalContext`. This is the automatic retrieval point.
2. **Stop** — fires after Claude responds. Read the transcript, enqueue recording job. This is the automatic recording point.

---

## Part 2: Architecture Design

### 2.1 Core Principle

**System-driven, not agent-driven.** Unlike OneContext (agent decides when to search) and GCC (agent calls CONTEXT manually), Focus automatically:
1. Records every conversation turn in the background (Stop hook)
2. Retrieves relevant context before every response (UserPromptSubmit hook)

The agent never needs to know the context system exists. It just always has the right background knowledge.

### 2.2 Recording Pipeline (Stop Hook)

```
Claude finishes responding
  → Stop hook fires
  → Read session_id, transcript_path, cwd from stdin
  → Enqueue recording job (fast, <200ms):
      Write to PostgreSQL jobs table OR
      Write signal file to ~/.focus/.signals/ as fallback
  → Exit 0 (non-blocking, async)

Background worker picks up job:
  1. Read raw JSONL transcript from ~/.claude/projects/<path>/*.jsonl
  2. Parse into turns (trace parentUUID chains, group by root timestamp)
  3. Content-hash each turn (MD5) for dedup — skip if already recorded
  4. Store full raw turn content in PostgreSQL (NOT just summaries)
  5. Generate turn summary via LLM (Haiku or local Ollama)
  6. Run entity extraction: people, projects, commitments, decisions mentioned
  7. Link to existing Focus entities (resolver)
  8. Generate/update session summary (aggregate turn summaries)
```

**Key difference from OneContext**: Focus stores the **full raw conversation** as the source of truth, not just summaries. Summaries are an index layer for fast retrieval, but LLMs can search and read the actual dialogue.

### 2.3 Retrieval Pipeline (UserPromptSubmit Hook)

```
User submits prompt
  → UserPromptSubmit hook fires
  → Read prompt from stdin JSON
  → Classify prompt (MUST be fast, <2 seconds total):
      - What project/domain/bucket is this about?
      - What type of context would help? (past conversations, emails, people, decisions)
  → Retrieve from PostgreSQL:
      - Relevant past conversation turns (by project + keyword/embedding similarity)
      - Relevant emails/documents (from existing Focus ingestion)
      - Relevant commitments/decisions
      - Relevant people context
  → Format as concise context block
  → Return via additionalContext JSON
  → Exit 0
```

**The classifier must be fast.** Options (in order of speed):
1. **Keyword/regex matching** (~10ms) — match project names, people names, known topics
2. **Embedding similarity** (~100ms) — pre-computed embeddings in Chroma, cosine similarity against prompt
3. **Local LLM** (~1-2s) — Ollama with small model for nuanced classification
4. **Hybrid** — keyword match first, fall back to embedding if no strong match

**The retrieval must be fast.** Pre-indexed queries against PostgreSQL + Chroma. No LLM calls during retrieval.

### 2.4 Storage Schema (PostgreSQL additions)

New tables to add to existing Focus schema:

```sql
-- Raw agent sessions
CREATE TABLE agent_sessions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id TEXT NOT NULL UNIQUE,        -- Claude Code session ID
    transcript_path TEXT,                    -- path to JSONL file
    workspace_path TEXT,                     -- project directory
    provider TEXT DEFAULT 'claude',          -- claude/codex/gemini
    session_title TEXT,                      -- LLM-generated
    session_summary TEXT,                    -- LLM-generated aggregate
    started_at TIMESTAMPTZ,
    last_activity_at TIMESTAMPTZ,
    project_id UUID REFERENCES projects(id), -- linked Focus project
    created_at TIMESTAMPTZ DEFAULT now()
);

-- Individual conversation turns
CREATE TABLE agent_turns (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id UUID REFERENCES agent_sessions(id),
    turn_number INTEGER NOT NULL,
    user_message TEXT,                       -- what the user said
    assistant_summary TEXT,                  -- LLM-generated summary
    turn_title TEXT,                         -- LLM-generated title
    content_hash TEXT NOT NULL,              -- MD5 for dedup
    model_name TEXT,                         -- which model responded
    started_at TIMESTAMPTZ,
    ended_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT now(),
    UNIQUE(session_id, turn_number)
);

-- Full raw turn content (separated for performance, like OneContext)
CREATE TABLE agent_turn_content (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    turn_id UUID REFERENCES agent_turns(id) UNIQUE,
    content TEXT NOT NULL,                   -- raw JSONL lines
    content_size INTEGER,
    created_at TIMESTAMPTZ DEFAULT now()
);

-- Entities extracted from conversations (links to existing Focus entities)
CREATE TABLE agent_turn_entities (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    turn_id UUID REFERENCES agent_turns(id),
    entity_type TEXT NOT NULL,               -- person, project, task, commitment, decision
    entity_id UUID,                          -- reference to Focus entity table
    entity_name TEXT,                        -- extracted name (for unresolved entities)
    confidence FLOAT,
    created_at TIMESTAMPTZ DEFAULT now()
);

-- Background job queue (like OneContext's, but in PostgreSQL)
CREATE TABLE focus_jobs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    kind TEXT NOT NULL,                      -- session_process, turn_summary, session_summary, entity_extract
    dedupe_key TEXT UNIQUE,                  -- for idempotent enqueue
    payload JSONB NOT NULL,
    status TEXT DEFAULT 'queued',            -- queued, processing, retry, done, failed
    priority INTEGER DEFAULT 10,
    attempts INTEGER DEFAULT 0,
    max_attempts INTEGER DEFAULT 10,
    locked_until TIMESTAMPTZ,
    error_message TEXT,
    created_at TIMESTAMPTZ DEFAULT now(),
    updated_at TIMESTAMPTZ DEFAULT now()
);
```

### 2.5 Full Flow Diagram

```
┌─────────────────────────────────────────────────────────────┐
│                    CLAUDE CODE SESSION                       │
│                                                             │
│  User types prompt ──→ UserPromptSubmit hook fires          │
│                              │                              │
│                    ┌─────────▼──────────┐                   │
│                    │  focus retrieve     │                   │
│                    │  --query "prompt"   │ <2s               │
│                    │                    │                   │
│                    │  1. Classify bucket │                   │
│                    │  2. Query Postgres  │                   │
│                    │  3. Query Chroma    │                   │
│                    │  4. Format context  │                   │
│                    └─────────┬──────────┘                   │
│                              │                              │
│                    additionalContext JSON                    │
│                              │                              │
│                    ┌─────────▼──────────┐                   │
│                    │  Claude responds    │                   │
│                    │  (has full context) │                   │
│                    └─────────┬──────────┘                   │
│                              │                              │
│                    Stop hook fires ──→ enqueue job           │
│                              │                              │
└──────────────────────────────┼──────────────────────────────┘
                               │
                    ┌──────────▼──────────┐
                    │  Background Worker   │
                    │                     │
                    │  1. Parse JSONL      │
                    │  2. Store raw turns  │
                    │  3. Summarize (LLM)  │
                    │  4. Extract entities │
                    │  5. Link to projects │
                    │  6. Update embeddings│
                    └─────────────────────┘

        ┌──────────────────────────────────────────┐
        │         UNIFIED FOCUS STORE              │
        │         (PostgreSQL + Chroma)            │
        │                                          │
        │  ┌─────────┐  ┌─────────┐  ┌─────────┐ │
        │  │ Emails   │  │ Agent   │  │ Docs    │ │
        │  │ & Texts  │  │ Convos  │  │ & Files │ │
        │  └────┬─────┘  └────┬────┘  └────┬────┘ │
        │       │             │             │      │
        │       ▼             ▼             ▼      │
        │  ┌──────────────────────────────────┐   │
        │  │  Shared entity layer:            │   │
        │  │  People, Projects, Tasks,        │   │
        │  │  Commitments, Decisions          │   │
        │  └──────────────────────────────────┘   │
        └──────────────────────────────────────────┘
```

### 2.6 CLI Commands

```bash
# Recording (runs automatically via hooks, but also manual)
focus record                        # manually trigger recording of current session
focus record --all                  # scan and record all unprocessed sessions

# Search (for manual deep dives, like OneContext's aline search)
focus search "pattern"              # broad regex across all sources
focus search "pattern" --type conv  # only agent conversations
focus search "pattern" --type email # only emails
focus search "pattern" --type all   # everything
focus search "pattern" --project X  # scoped to project
focus search --turn <id>            # show full turn content
focus search --session <id>         # show session with all turns

# Context (for debugging what the hook injects)
focus context --query "some prompt" # preview what context would be injected
focus context --show                # show current project detection
focus context --stats               # show recording stats (sessions, turns, etc.)

# Worker management
focus worker start                  # start background worker
focus worker stop
focus worker status
```

### 2.7 Hook Installation

Focus should install hooks into `~/.claude/settings.json` (NOT as plugins, due to known bugs):

```json
{
  "hooks": {
    "UserPromptSubmit": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "focus retrieve --hook"
          }
        ]
      }
    ],
    "Stop": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "focus record --hook --async"
          }
        ]
      }
    ],
    "SessionStart": [
      {
        "matcher": "startup|resume",
        "hooks": [
          {
            "type": "command",
            "command": "focus context --session-start"
          }
        ]
      }
    ]
  }
}
```

The `focus retrieve --hook` command:
1. Reads stdin JSON (gets prompt, session_id, cwd)
2. Classifies the prompt (project/domain/bucket)
3. Queries PostgreSQL + Chroma for relevant context
4. Outputs JSON with `additionalContext`
5. Must complete in <2 seconds

The `focus record --hook --async` command:
1. Reads stdin JSON (gets session_id, transcript_path, cwd)
2. Enqueues a `session_process` job in PostgreSQL
3. Exits immediately (worker processes in background)
4. Must complete in <200ms

The `focus context --session-start` command:
1. Reads stdin JSON (gets cwd)
2. Detects project from cwd
3. Returns broad project context (recent sessions, active sprint, key people)
4. Output via `additionalContext`

---

## Part 3: Implementation Plan

### Phase 1: Recording Infrastructure
1. Add `agent_sessions`, `agent_turns`, `agent_turn_content`, `focus_jobs` tables to schema.sql
2. Add SQLAlchemy models for new tables in `src/storage/models.py`
3. Write JSONL transcript parser (`src/ingestion/claude_code.py` — file already exists, may need rewrite)
   - Parse Claude Code JSONL format
   - Trace parentUUID chains to identify turns
   - Extract user messages and assistant responses
   - Content-hash for dedup
4. Write recording CLI command (`src/cli/record_cmd.py`)
   - `focus record --hook` reads stdin, enqueues job
   - `focus record --all` scans all unprocessed sessions
5. Write background worker (`src/daemon.py` — file already exists)
   - Poll `focus_jobs` table
   - Process `session_process` jobs: parse → store → summarize → extract entities
   - Lease-based locking, exponential backoff
6. Write Stop hook script that calls `focus record --hook`

### Phase 2: Retrieval Infrastructure
7. Write prompt classifier (`src/processing/classifier.py` — file already exists)
   - Fast project/domain detection from prompt text
   - Keyword matching against known projects, people, topics
   - Optional: embedding similarity via Chroma
8. Write context retriever (`src/processing/retriever.py` — new file)
   - Given a project/domain classification, query for relevant:
     - Past conversation turns (summaries + raw if needed)
     - Emails and documents
     - Commitments and decisions
     - People context
   - Rank by relevance and recency
   - Format as concise context block (respect token budget)
9. Write retrieval CLI command (`src/cli/retrieve_cmd.py`)
   - `focus retrieve --hook` reads stdin, classifies, retrieves, outputs JSON
   - `focus context --query "..."` for manual preview
10. Write UserPromptSubmit hook script
11. Write SessionStart hook script

### Phase 3: Integration
12. Write hook installer (`focus init` or `focus hooks install`)
    - Adds hooks to `~/.claude/settings.json`
    - Non-destructive (preserves existing hooks)
13. Write `focus search` CLI for manual deep dives
14. Connect conversation entities to existing Focus entity graph (people, projects, tasks)
15. Tests for everything (per CLAUDE.md conventions)

### Phase 4: Refinements
16. Token budget management — ensure injected context doesn't overwhelm the prompt
17. Relevance tuning — adjust classifier and retriever for precision
18. Session-level project detection — auto-link sessions to Focus projects by cwd
19. Cross-source retrieval — when searching conversations, also surface related emails and vice versa
20. Conversation-aware CLAUDE.md generation — include recent conversation context in generated CLAUDE.md

---

## Part 4: Key Design Decisions

### Store full raw conversations, not just summaries
Summaries are lossy. The raw JSONL is the source of truth. Summaries serve as an index layer for fast retrieval, but when an LLM needs deep context, it should read the actual dialogue. Store raw content in `agent_turn_content` (separated table for query performance, like OneContext does).

### System-driven retrieval, not agent-driven
Do NOT rely on the agent deciding to search. The UserPromptSubmit hook fires automatically on every prompt and injects relevant context. The agent doesn't even know the system exists — it just always has good context. This is fundamentally different from OneContext (agent must invoke skill) and GCC (agent must call CONTEXT).

### Fast classifier, not deep analysis
The UserPromptSubmit hook must complete in <2 seconds. Use keyword/regex matching against known project names, people names, and topics as the primary classifier. Fall back to embedding similarity only if needed. Never call an LLM during retrieval — that's too slow for a hook.

### PostgreSQL, not SQLite
Focus already uses PostgreSQL. Keep everything in one store. This also enables better concurrent access (worker + hook querying simultaneously) vs SQLite's write locking.

### Respect token budgets
The `additionalContext` injected by the hook shouldn't overwhelm Claude's context. Budget roughly:
- Session start context: ~500 tokens (project overview, recent sessions)
- Per-prompt context: ~1000-2000 tokens (relevant turns, emails, decisions)
- Include summaries by default, raw content only when highly relevant
- Always include source references so the agent can `focus search --turn <id>` for more

### The `focus search` CLI is a fallback, not the primary mechanism
Like OneContext's `aline search`, this is for when the agent (or user) wants to manually dig deeper. The automatic injection handles 90% of cases. The CLI handles the remaining 10%.

---

## Part 5: References

- **OneContext**: https://github.com/TheAgentContextLab/OneContext (public repo, no license)
  - Internal name: Aline (PyPI: `aline-ai`, module: `realign`)
  - npm: `onecontext-ai`
- **GCC Paper**: arXiv:2508.00031v1, "Git Context Controller: Manage the Context of LLM-based Agents like Git"
  - Code: https://github.com/theworldofagents/GCC
- **Claude Code Hooks Docs**: https://docs.anthropic.com/en/docs/claude-code/hooks
- **Key GitHub Issues**:
  - #13912 — UserPromptSubmit stdout caused errors (fixed)
  - #12151 — Plugin hook output silently discarded (was open Jan 2026)
  - #14281 — additionalContext injected multiple times (fixed v2.1)
- **Existing Focus files to modify**:
  - `src/ingestion/claude_code.py` — JSONL parser (exists, may need rewrite)
  - `src/processing/classifier.py` — classifier (exists, extend for prompt classification)
  - `src/storage/models.py` — ORM models (add new tables)
  - `src/storage/db.py` — database layer (add new queries)
  - `src/daemon.py` — background worker (exists, extend for conversation processing)
  - `src/cli/main.py` — CLI entry point (add new commands)
  - `schema.sql` — database schema (add new tables)

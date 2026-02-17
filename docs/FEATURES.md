# Focus — Feature Registry

> This file is the single source of truth for what Focus does.
> Every feature is listed here. If it's not here, it doesn't exist.
> Update this file BEFORE building or changing any feature.

Last updated: 2026-02-17
Total features: 20 (9 MVP, 11 post-MVP) — 19 DONE, 1 PLANNED

---

## F-001: Gmail Ingestion
- **Status**: DONE | MVP
- **Phase**: 1 (Foundation)
- **What**: Connect to Gmail via OAuth, fetch emails incrementally using historyId
- **Inputs**: Google OAuth credentials, email account config
- **Outputs**: Raw emails in `raw_interactions` + processed rows in `emails` table
- **Depends on**: F-003 (Multi-Account Email)
- **Depended on by**: F-004 (Classification), F-005 (Extraction)
- **Key files**: `src/ingestion/gmail.py`
- **Notes**: Supports multiple accounts. Each account has its own OAuth token and sync cursor. Full sync and incremental sync via historyId both implemented.

## F-002: Google Drive Ingestion
- **Status**: DONE | MVP
- **Phase**: 2 (Core Features)
- **What**: Sync documents from Google Drive via Changes API
- **Inputs**: Google OAuth credentials (shared with Gmail)
- **Outputs**: Raw docs in `raw_interactions` + processed rows in `documents` table
- **Depends on**: F-003 (Multi-Account Email, for shared OAuth)
- **Depended on by**: F-008 (Vault Generation)
- **Key files**: `src/ingestion/drive.py`
- **Notes**: Full sync (files.list) and incremental sync (Changes API with pageToken). Exports Google Docs/Sheets/Slides as text. Downloads non-Google text files under 5MB. Content-hash dedup to avoid reprocessing unchanged files. Folder path resolution with caching. Integrated into pipeline, daemon, CLI sync, and REST API. Config: `sync.drive_enabled`.

## F-003: Multi-Account Email
- **Status**: DONE | MVP
- **What**: Support multiple email accounts with per-account priority weights and processing rules
- **Inputs**: User adds accounts via `focus account add`
- **Outputs**: `email_accounts` table rows, per-account OAuth tokens
- **Depends on**: Nothing
- **Depended on by**: F-001 (Gmail), F-002 (Drive), F-010 (Priority Scoring)
- **Key files**: `src/ingestion/accounts.py`, `src/cli/account.py`
- **Notes**: Full CLI for add/list/priority/enable/disable/auth. Tokens stored in DB + disk fallback.

## F-004: Email Classification
- **Status**: DONE | MVP
- **What**: Classify emails as human/automated/newsletter/spam/system using local LLM
- **Inputs**: Raw email from ingestion
- **Outputs**: Classification label + confidence + routing decision
- **Depends on**: F-001 (Gmail Ingestion)
- **Depended on by**: F-005 (Extraction), F-006 (Regex Parse)
- **Key files**: `src/processing/classifier.py`
- **Model**: Ollama + Qwen3 4B ($0, uses /no_think mode for speed)
- **Notes**: Routes human→deep_analysis, automated→regex_parse, newsletter→archive, spam/system→skip.

## F-005: Deep Extraction (Human Emails)
- **Status**: DONE | MVP
- **What**: Extract tasks, commitments, questions, people, projects from human emails
- **Inputs**: Human-classified emails + known projects/people context
- **Outputs**: Structured extraction JSON → tasks, commitments, people tables
- **Depends on**: F-004 (Classification)
- **Depended on by**: F-007 (Entity Resolution), F-008 (Vault), F-009 (CLAUDE.md)
- **Key files**: `src/processing/extractor.py`
- **Model**: Claude Haiku (~$0.0003/email)
- **Notes**: Extracts tasks, commitments, questions, waiting_on, project_links, people, sentiment, reply suggestions. All AI calls logged in ai_conversations.

## F-006: Regex Parse (Automated Emails)
- **Status**: DONE | MVP
- **What**: Extract order numbers, tracking, amounts from automated emails
- **Inputs**: Automated-classified emails
- **Outputs**: Structured data in `emails.extraction_result`
- **Depends on**: F-004 (Classification)
- **Depended on by**: F-008 (Vault — Automated inbox view)
- **Key files**: `src/processing/regex_parser.py`
- **Notes**: Detects UPS/USPS/FedEx tracking, order numbers, dollar amounts, dates, statuses. Auto-categorizes as order/shipping/billing/alert/subscription.

## F-007: Entity Resolution
- **Status**: DONE | MVP
- **What**: Fuzzy-match people and projects across sources, dedup, create new entities
- **Inputs**: Extraction results with raw names/references
- **Outputs**: Linked foreign keys in tasks, commitments, emails tables
- **Depends on**: F-005 (Extraction)
- **Depended on by**: F-008 (Vault), F-009 (CLAUDE.md)
- **Key files**: `src/processing/resolver.py`
- **Notes**: Uses SequenceMatcher for fuzzy name matching. Extracts email/name from From headers. Auto-creates people and projects when no match found. Links people to projects.

## F-008: Obsidian Vault Generation
- **Status**: DONE | MVP
- **What**: Generate the full vault directory structure from DB state
- **Inputs**: All DB tables
- **Outputs**: Markdown files in vault/ (README, KANBAN, PEOPLE, DECISIONS, EMAILS, etc.)
- **Depends on**: F-005, F-006, F-007
- **Depended on by**: F-009 (CLAUDE.md references vault paths)
- **Key files**: `src/output/vault.py`, `src/output/kanban.py`, `src/output/daily.py`, `src/output/drafts.py`
- **Notes**: Generates full directory structure: Domains (life_thread), Projects (complex), SimpleProjects (simple), People, Inbox (NeedsReply/Waiting/FYI/Automated), Me, Daily. Per-project KANBAN.md, PEOPLE.md, DECISIONS.md, EMAILS.md, TIMELINE.md.

## F-009: CLAUDE.md Generation
- **Status**: DONE | MVP
- **What**: Generate machine-readable project briefing at project root
- **Inputs**: DB state (tasks, decisions, people, sprints, preferences)
- **Outputs**: CLAUDE.md at project root
- **Depends on**: F-005, F-007, F-010
- **Depended on by**: Nothing (end of chain, consumed by Claude Code)
- **Key files**: `src/output/claude_md.py`
- **Notes**: Inlines current sprint, blockers, active sprint, conventions, people. References vault paths for deep context. Regenerates on sync, generate, sprint change, priority change.

## F-010: User Priority System
- **Status**: DONE | Post-MVP
- **What**: User-set pins, priorities, deadlines that override AI scoring
- **Inputs**: CLI commands (focus project pin, focus task priority, etc.)
- **Outputs**: Updated project/task rows, effective priority recalculation
- **Depends on**: F-003 (account weights)
- **Depended on by**: F-009 (CLAUDE.md), F-008 (daily notes)
- **Key files**: `src/cli/project.py`, `src/cli/task_cmd.py`, `src/priority.py`
- **Notes**: Effective priority = f(user_pinned, user_priority, deadline_urgency, sprint_boost, account_weight, AI_score). Supports scope filtering (all/today/week).

## F-011: Sprints
- **Status**: DONE | Post-MVP
- **What**: Time-bounded priority boosts with auto-archive on expiry
- **Inputs**: CLI (focus sprint create/list/deactivate)
- **Outputs**: `sprints` table rows, priority multipliers, auto-archive actions
- **Depends on**: F-010 (Priority System)
- **Depended on by**: F-009 (CLAUDE.md shows active sprint)
- **Key files**: `src/cli/sprint_cmd.py`, `src/priority.py`
- **Notes**: Sprints boost linked project by configurable multiplier. Auto-expire and archive project when sprint ends. Shown in daily notes and CLAUDE.md.

## F-012: Raw Interaction Archive
- **Status**: DONE | MVP
- **What**: Store every raw interaction permanently for future reprocessing
- **Inputs**: All ingested data (emails, messages, docs, AI calls)
- **Outputs**: `raw_interactions` table, `ai_conversations` table
- **Depends on**: Nothing
- **Depended on by**: F-013 (Reprocessing)
- **Key files**: `src/storage/raw.py`
- **Notes**: Content-hash deduplication. Every AI API call logged with full request/response, token counts, costs, model version. Supports querying unprocessed interactions by version.

## F-013: Reprocessing Pipeline
- **Status**: DONE | Post-MVP
- **What**: Re-extract structured data from raw interactions using current/better models
- **Inputs**: Raw interactions + new model/prompt version
- **Outputs**: Updated extraction results, refreshed structured tables
- **Depends on**: F-012 (Raw Archive)
- **Depended on by**: Nothing
- **Key files**: `src/cli/main.py` (reprocess command), `src/storage/raw.py`
- **CLI**: `focus reprocess --since DATE --dry-run`

## F-014: Email Draft Queue
- **Status**: DONE | Post-MVP
- **What**: Suggest email replies based on extraction + user style
- **Inputs**: Emails needing reply + extraction results
- **Outputs**: EMAIL-DRAFTS.md in vault
- **Depends on**: F-005 (Extraction)
- **Depended on by**: F-008 (Vault)
- **Key files**: `src/output/drafts.py`
- **Notes**: Sorted by urgency, shows why reply is needed, includes suggested reply text.

## F-015: iMessage Ingestion
- **Status**: PLANNED | Post-MVP
- **What**: Read iMessage SQLite DB on macOS
- **Inputs**: ~/Library/Messages/chat.db
- **Outputs**: Messages in `messages` table + `raw_interactions`
- **Depends on**: Nothing (but macOS only)
- **Key files**: `src/ingestion/imessage.py`

## F-016: Daemon Mode
- **Status**: DONE | Post-MVP
- **What**: Run continuously, syncing and regenerating on interval
- **Inputs**: Config (sync interval)
- **Outputs**: Periodic sync + vault regeneration
- **Depends on**: F-001, F-008, F-009
- **Key files**: `src/daemon.py`
- **CLI**: `focus daemon --interval 15`
- **Notes**: Handles SIGINT/SIGTERM gracefully. Expires sprints, syncs accounts, processes emails, regenerates vault on each cycle.

## F-017: REST API
- **Status**: DONE | Post-MVP
- **What**: FastAPI endpoints for querying data, triggering syncs
- **Inputs**: HTTP requests
- **Outputs**: JSON responses
- **Depends on**: All storage features
- **Key files**: `src/api/routes.py`
- **Notes**: Endpoints: /health, /projects, /tasks, /people, /emails, /priorities, /sync, /generate. Auto-docs at /docs.

## F-018: Semantic Search
- **Status**: DONE | Post-MVP
- **What**: Search across all data using Chroma vector embeddings
- **Inputs**: Query string
- **Outputs**: Ranked results from emails, docs, projects, raw interactions
- **Depends on**: F-012 (Raw Archive), Chroma
- **Key files**: `src/storage/vectors.py`
- **CLI**: `focus search "query" --semantic`, `focus reindex`
- **API**: `GET /search?q=query&collections=emails,documents&limit=10`
- **Notes**: VectorStore class with lazy Chroma init (module importable without chromadb). 4 collections: emails, documents, projects, raw_interactions. Cosine similarity. `reindex` rebuilds all indexes from DB (raw capped at 5000 most recent). Pipeline auto-indexes emails after processing. Graceful fallback: semantic search falls back to text search on error. Config: `general.chroma_path`.

## F-019: Claude Code Session Capture
- **Status**: DONE | Post-MVP
- **What**: Scan Claude Code JSONL session files, archive transcripts, extract decisions via Haiku
- **Inputs**: `~/.claude/projects/*/` JSONL session files
- **Outputs**: Sessions + decisions in `raw_interactions` table
- **Depends on**: F-012 (Raw Archive), F-009 (CLAUDE.md)
- **Key files**: `src/ingestion/claude_code.py`
- **CLI**: `focus capture [--project DIR] [--no-extract]`
- **API**: `POST /capture?project_dir=...&extract=true`
- **Notes**: Parses JSONL format, filters to meaningful user/assistant turns (skips sidechains, meta, commands, short messages). Builds condensed transcript for LLM. Decision extraction uses Claude Haiku with structured JSON output. Stores session transcript and decisions as separate raw_interactions with content-hash dedup. Only extracts from sessions with 3+ turns. Integrated into daemon (auto-scans each cycle). Skips already-ingested sessions.

## F-020: Claude Code Skills System
- **Status**: DONE | Post-MVP
- **What**: Auto-generate, search, and manage Claude Code skills (SKILL.md files)
- **Inputs**: Completed sessions (auto), user description (manual), GitHub repos (search)
- **Outputs**: SKILL.md files in `~/.claude/skills/` or `.claude/skills/`
- **Depends on**: F-019 (Session Capture), Anthropic API
- **Key files**: `src/skills/generator.py`, `src/skills/analyzer.py`, `src/skills/registry.py`, `src/skills/installer.py`, `src/cli/skill_cmd.py`
- **CLI**: `focus skill create|list|show|search|install|uninstall|auto-scan`
- **Notes**: Three modes: (1) Auto-generate from successful sessions — quality gate (score >= 0.6, daily limit of 3), triggers after session_summary job via skill_extract worker job. (2) Manual creation — `focus skill create "description"` calls Haiku to generate instructions. (3) Public registry search — searches GitHub repos (anthropics/skills, awesome-lists) and installs SKILL.md files. All skills follow Agent Skills standard with YAML frontmatter. Tracks generated skills in `generated_skills` DB table for dedup. **Context injection**: Installed skills are automatically surfaced via the UserPromptSubmit hook when Focus's keyword classifier detects relevance — skill name, description, and body are matched against prompt keywords, project context, and file paths. Injected as `[Skill]` context blocks with truncated instructions and path reference. 106 tests.

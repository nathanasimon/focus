# Architecture

```
src/
├── ingestion/      # Gmail, Drive connectors
│   ├── gmail.py    # OAuth + incremental sync via historyId
│   └── accounts.py # Multi-account management
├── processing/     # Tiered AI pipeline
│   ├── classifier.py   # Ollama + Qwen3 4B (local, $0)
│   ├── extractor.py    # Claude Haiku (tasks, commitments, people)
│   ├── regex_parser.py # Automated email parsing ($0)
│   └── resolver.py     # Entity resolution + project linking
├── storage/        # Data layer
│   ├── db.py       # PostgreSQL via SQLAlchemy (async)
│   ├── models.py   # ORM models
│   └── raw.py      # Raw interaction archive
├── output/         # Markdown generation
│   ├── vault.py    # Obsidian vault generator
│   ├── kanban.py   # Per-project kanban boards
│   ├── daily.py    # Daily notes
│   ├── drafts.py   # Email draft suggestions
│   └── claude_md.py # CLAUDE.md generator
├── context/        # Claude Code context system
│   ├── classifier.py    # Prompt classification (local regex)
│   ├── retriever.py     # Context block retrieval from DB
│   ├── formatter.py     # Token-budget-aware formatting
│   ├── worker.py        # Background job processor
│   ├── project_state.py # Active project selection
│   └── artifact_extractor.py # JSONL artifact parser
├── api/            # FastAPI REST endpoints
├── cli/            # Typer CLI (focus command)
└── daemon.py       # Background sync daemon
```

Key patterns: async throughout, SQLAlchemy 2.0 style, Pydantic models for all data, raw interactions stored permanently for reprocessing.

"""Focus CLI — main entry point using Typer."""

import asyncio
import logging
from typing import Optional

import typer
from rich.console import Console
from rich.logging import RichHandler

from src.cli.account import app as account_app
from src.cli.context_cmd import app as context_app
from src.cli.generate import app as generate_app
from src.cli.hooks_cmd import app as hooks_app
from src.cli.priority_cmd import app as priority_app
from src.cli.project import app as project_app
from src.cli.record_cmd import app as record_app
from src.cli.retrieve_cmd import app as retrieve_app
from src.cli.sprint_cmd import app as sprint_app
from src.cli.sync_cmd import app as sync_app
from src.cli.task_cmd import app as task_app
from src.cli.worker_cmd import app as worker_app

app = typer.Typer(
    name="focus",
    help="Your second brain that actually builds itself.",
    no_args_is_help=True,
)
console = Console()

# Register subcommands
app.add_typer(account_app, name="account", help="Manage email accounts")
app.add_typer(sync_app, name="sync", help="Sync data from sources")
app.add_typer(generate_app, name="generate", help="Regenerate vault and CLAUDE.md")
app.add_typer(project_app, name="project", help="Manage projects")
app.add_typer(task_app, name="task", help="Manage tasks")
app.add_typer(sprint_app, name="sprint", help="Manage sprints")
app.add_typer(priority_app, name="priorities", help="View priority rankings")
app.add_typer(record_app, name="record", help="Record Claude Code conversations")
app.add_typer(retrieve_app, name="retrieve", help="Retrieve context for prompts")
app.add_typer(context_app, name="context", help="Context retrieval and debugging")
app.add_typer(hooks_app, name="hooks", help="Install/manage Claude Code hooks")
app.add_typer(worker_app, name="worker", help="Manage context worker")


def _setup_logging(verbose: bool = False):
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(message)s",
        handlers=[RichHandler(rich_tracebacks=True, show_time=False)],
    )


@app.command()
def init(
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Enable debug logging"),
):
    """Initialize Focus — first-time setup wizard."""
    _setup_logging(verbose)

    async def _init():
        from pathlib import Path

        from src.config import get_settings
        from src.storage.db import init_db

        settings = get_settings()

        console.print("[bold]Welcome to Focus[/bold]", style="green")
        console.print("Setting up your second brain...\n")

        # Create config directory
        config_dir = Path.home() / ".config/focus"
        config_dir.mkdir(parents=True, exist_ok=True)
        console.print(f"  Config dir: {config_dir}")

        # Create vault directory
        vault_path = settings.general.vault_path
        Path(vault_path).expanduser().mkdir(parents=True, exist_ok=True)
        console.print(f"  Vault path: {vault_path}")

        # Initialize database
        console.print("  Initializing database...")
        await init_db()
        console.print("  Database ready.")

        # Write default config if it doesn't exist
        config_path = config_dir / "config.toml"
        if not config_path.exists():
            config_path.write_text(
                '[general]\nvault_path = "~/Focus-Vault"\n'
                'db_url = "postgresql+asyncpg://localhost/focus"\n'
                'log_level = "INFO"\n\n'
                "[anthropic]\n"
                '# api_key = ""  # Or set ANTHROPIC_API_KEY env var\n'
                'model = "claude-haiku-4-5-20251001"\n\n'
                "[ollama]\n"
                'model = "qwen3:4b"\n'
                'base_url = "http://localhost:11434"\n\n'
                "[sync]\n"
                "interval_minutes = 15\n"
                "drive_enabled = true\n\n"
                "[raw_storage]\n"
                "enabled = true\n"
                "store_ai_conversations = true\n"
                "retention_days = -1\n"
            )
            console.print(f"  Config written: {config_path}")

        # Auto-install Claude Code hooks
        from src.cli.hooks_cmd import (
            _has_focus_hook,
            _read_settings,
            _write_settings,
            get_focus_hooks,
        )

        claude_settings = _read_settings()
        claude_hooks = claude_settings.get("hooks", {})
        hooks_installed = 0
        for event_name, focus_entry in get_focus_hooks().items():
            existing = claude_hooks.get(event_name, [])
            if not _has_focus_hook(existing):
                existing.append(focus_entry)
                claude_hooks[event_name] = existing
                hooks_installed += 1
        if hooks_installed > 0:
            claude_settings["hooks"] = claude_hooks
            _write_settings(claude_settings)
            console.print(f"  Claude Code hooks: {hooks_installed} installed")
        else:
            console.print("  Claude Code hooks: already configured")

        console.print("\n[bold green]Focus initialized![/bold green]")
        console.print("\nNext steps:")
        console.print("  1. Add an email account: [cyan]focus account add[/cyan]")
        console.print("  2. Sync your emails:     [cyan]focus sync[/cyan]")
        console.print("  3. Generate your vault:   [cyan]focus generate[/cyan]")

    asyncio.run(_init())


@app.command()
def status(
    verbose: bool = typer.Option(False, "--verbose", "-v"),
):
    """Show sync state, counts, and errors."""
    _setup_logging(verbose)

    async def _status():
        from sqlalchemy import func, select

        from src.storage.db import get_session
        from src.storage.models import (
            Commitment,
            Document,
            Email,
            EmailAccount,
            Person,
            Project,
            RawInteraction,
            SyncState,
            Task,
        )

        async with get_session() as session:
            # Counts
            counts = {}
            for model, name in [
                (EmailAccount, "accounts"),
                (Email, "emails"),
                (Document, "documents"),
                (Person, "people"),
                (Project, "projects"),
                (Task, "tasks"),
                (Commitment, "commitments"),
                (RawInteraction, "raw_interactions"),
            ]:
                result = await session.execute(select(func.count()).select_from(model))
                counts[name] = result.scalar()

            # Classification breakdown
            result = await session.execute(
                select(Email.classification, func.count())
                .group_by(Email.classification)
            )
            classifications = {row[0] or "unprocessed": row[1] for row in result.all()}

            # Sync states
            result = await session.execute(select(SyncState))
            syncs = result.scalars().all()

            # Display
            console.print("\n[bold]Focus Status[/bold]\n")

            from rich.table import Table

            table = Table(title="Data Counts")
            table.add_column("Entity", style="cyan")
            table.add_column("Count", style="green", justify="right")
            for name, count in counts.items():
                table.add_row(name, str(count))
            console.print(table)

            if classifications:
                console.print("\n[bold]Email Classification:[/bold]")
                for cls, count in sorted(classifications.items()):
                    console.print(f"  {cls}: {count}")

            if syncs:
                console.print("\n[bold]Sync State:[/bold]")
                for s in syncs:
                    status_icon = "[green]OK[/green]" if s.status == "ok" else f"[red]{s.status}[/red]"
                    last = s.last_sync.strftime("%Y-%m-%d %H:%M") if s.last_sync else "never"
                    console.print(f"  {s.id}: {status_icon} (last: {last})")

    asyncio.run(_status())


@app.command()
def daemon(
    interval: int = typer.Option(15, "--interval", "-i", help="Sync interval in minutes"),
    verbose: bool = typer.Option(False, "--verbose", "-v"),
):
    """Run Focus as a background daemon (sync + generate on interval)."""
    _setup_logging(verbose)

    from src.daemon import run_daemon

    asyncio.run(run_daemon(interval_minutes=interval))


@app.command()
def search(
    query: str = typer.Argument(help="Search query"),
    type: Optional[str] = typer.Option(None, "--type", "-t", help="Filter: conv, email, task, all"),
    semantic: bool = typer.Option(False, "--semantic", "-s", help="Use vector semantic search"),
    limit: int = typer.Option(10, "--limit", "-n", help="Max results"),
    turn: Optional[str] = typer.Option(None, "--turn", help="Show full content for a turn ID"),
    session_id: Optional[str] = typer.Option(None, "--session", help="Show session with all turns"),
    verbose: bool = typer.Option(False, "--verbose", "-v"),
):
    """Search across all data (text or semantic)."""
    _setup_logging(verbose)

    async def _search():
        if turn:
            await _show_turn(turn)
        elif session_id:
            await _show_session(session_id)
        elif semantic:
            await _semantic_search(query, limit)
        elif type == "conv":
            await _search_conversations(query, limit)
        else:
            await _text_search(query, limit, include_conv=(type in (None, "all")))

    async def _semantic_search(q: str, n: int):
        try:
            from src.storage.vectors import semantic_search

            console.print(f"\n[bold]Semantic search: {q}[/bold]\n")

            results = await semantic_search(q, n_results=n)
            if not results:
                console.print("[yellow]No results found. Run 'focus reindex' to build the search index.[/yellow]")
                return

            for r in results:
                score = 1 - r["distance"]  # Convert distance to similarity
                label = r["collection"].replace("_", " ").title()
                preview = (r["text"] or "")[:150].replace("\n", " ")
                console.print(f"  [cyan][{label}][/cyan] ({score:.0%}) {preview}")

        except ImportError:
            console.print("[red]chromadb not installed. Run: pip install chromadb[/red]")
        except Exception as e:
            console.print(f"[red]Semantic search error: {e}[/red]")
            console.print("Falling back to text search...")
            await _text_search(q, n)

    async def _search_conversations(q: str, n: int):
        from sqlalchemy import or_, select
        from sqlalchemy.orm import selectinload

        from src.storage.db import get_session
        from src.storage.models import AgentSession, AgentTurn

        async with get_session() as session:
            console.print(f"\n[bold]Searching conversations for: {q}[/bold]\n")

            result = await session.execute(
                select(AgentTurn)
                .join(AgentSession)
                .options(selectinload(AgentTurn.session))
                .where(
                    or_(
                        AgentTurn.user_message.ilike(f"%{q}%"),
                        AgentTurn.assistant_summary.ilike(f"%{q}%"),
                        AgentTurn.turn_title.ilike(f"%{q}%"),
                    )
                )
                .order_by(AgentTurn.started_at.desc().nulls_last())
                .limit(n)
            )
            turns = result.scalars().all()

            if turns:
                console.print("[cyan]Conversations:[/cyan]")
                for t in turns:
                    title = t.turn_title or (t.user_message or "")[:60]
                    sid = t.session.session_id[:12] if t.session else "?"
                    console.print(f"  [{sid}] {title}")
            else:
                console.print("[yellow]No conversation results found.[/yellow]")

    async def _show_turn(turn_id: str):
        import uuid

        from sqlalchemy.orm import selectinload

        from src.storage.db import get_session
        from src.storage.models import AgentTurn

        async with get_session() as session:
            turn = await session.get(
                AgentTurn, uuid.UUID(turn_id),
                options=[selectinload(AgentTurn.content), selectinload(AgentTurn.session)],
            )
            if not turn:
                console.print(f"[red]Turn {turn_id} not found.[/red]")
                return

            console.print(f"\n[bold]Turn #{turn.turn_number}[/bold]")
            if turn.session:
                console.print(f"  Session: {turn.session.session_id[:12]}")
            if turn.turn_title:
                console.print(f"  Title:   {turn.turn_title}")
            console.print(f"  Model:   {turn.model_name or '?'}")
            console.print(f"  Tools:   {', '.join(turn.tool_names or []) or 'none'}")
            console.print()

            if turn.user_message:
                console.print("[bold]User:[/bold]")
                console.print(turn.user_message[:2000])
                console.print()

            if turn.content and turn.content.assistant_text:
                console.print("[bold]Assistant:[/bold]")
                console.print(turn.content.assistant_text[:2000])

    async def _show_session(sid: str):
        from sqlalchemy import select
        from sqlalchemy.orm import selectinload

        from src.storage.db import get_session
        from src.storage.models import AgentSession

        async with get_session() as session:
            result = await session.execute(
                select(AgentSession)
                .options(selectinload(AgentSession.turns))
                .where(AgentSession.session_id.ilike(f"%{sid}%"))
                .limit(1)
            )
            agent_session = result.scalar_one_or_none()

            if not agent_session:
                console.print(f"[red]Session matching '{sid}' not found.[/red]")
                return

            console.print(f"\n[bold]Session: {agent_session.session_id[:20]}[/bold]")
            console.print(f"  Workspace: {agent_session.workspace_path or '?'}")
            console.print(f"  Turns:     {agent_session.turn_count}")
            if agent_session.session_summary:
                console.print(f"  Summary:   {agent_session.session_summary[:200]}")
            console.print()

            from rich.table import Table

            table = Table(title="Turns")
            table.add_column("#", style="dim", width=4)
            table.add_column("Title / User Message", style="cyan")
            table.add_column("Tools", style="dim")

            for turn in sorted(agent_session.turns, key=lambda t: t.turn_number):
                title = turn.turn_title or (turn.user_message or "")[:60]
                tools = ", ".join(turn.tool_names or [])[:30]
                table.add_row(str(turn.turn_number), title, tools)

            console.print(table)

    async def _text_search(q: str, n: int, include_conv: bool = True):
        from sqlalchemy import or_, select

        from src.storage.db import get_session
        from src.storage.models import Document, Email, Person, Project, Task

        async with get_session() as session:
            console.print(f"\n[bold]Searching for: {q}[/bold]\n")

            # Search documents
            result = await session.execute(
                select(Document).where(
                    or_(
                        Document.title.ilike(f"%{q}%"),
                        Document.extracted_text.ilike(f"%{q}%"),
                    )
                ).limit(n)
            )
            docs = result.scalars().all()
            if docs:
                console.print("[cyan]Documents:[/cyan]")
                for d in docs:
                    path = f" ({d.folder_path})" if d.folder_path else ""
                    console.print(f"  {d.title}{path}")

            # Search projects
            result = await session.execute(
                select(Project).where(
                    or_(
                        Project.name.ilike(f"%{q}%"),
                        Project.description.ilike(f"%{q}%"),
                    )
                ).limit(n)
            )
            projects = result.scalars().all()
            if projects:
                console.print("[cyan]Projects:[/cyan]")
                for p in projects:
                    console.print(f"  {p.name} ({p.slug}) — {p.status}")

            # Search tasks
            result = await session.execute(
                select(Task).where(
                    or_(
                        Task.title.ilike(f"%{q}%"),
                        Task.description.ilike(f"%{q}%"),
                    )
                ).limit(n)
            )
            tasks = result.scalars().all()
            if tasks:
                console.print("\n[cyan]Tasks:[/cyan]")
                for t in tasks:
                    console.print(f"  [{t.status}] {t.title}")

            # Search people
            result = await session.execute(
                select(Person).where(
                    or_(
                        Person.name.ilike(f"%{q}%"),
                        Person.email.ilike(f"%{q}%"),
                    )
                ).limit(n)
            )
            people = result.scalars().all()
            if people:
                console.print("\n[cyan]People:[/cyan]")
                for p in people:
                    console.print(f"  {p.name} ({p.email or 'no email'})")

            # Search emails
            result = await session.execute(
                select(Email).where(
                    or_(
                        Email.subject.ilike(f"%{q}%"),
                        Email.snippet.ilike(f"%{q}%"),
                    )
                ).limit(n)
            )
            emails = result.scalars().all()
            if emails:
                console.print("\n[cyan]Emails:[/cyan]")
                for e in emails:
                    date_str = e.email_date.strftime("%Y-%m-%d") if e.email_date else "?"
                    console.print(f"  [{date_str}] {e.subject or '(no subject)'}")

            if not any([docs, projects, tasks, people, emails]):
                console.print("[yellow]No results found.[/yellow]")

        # Also search conversations if included
        if include_conv:
            await _search_conversations(q, n)

    asyncio.run(_search())


@app.command()
def reindex(
    verbose: bool = typer.Option(False, "--verbose", "-v"),
):
    """Rebuild the semantic search index from database."""
    _setup_logging(verbose)

    async def _reindex():
        try:
            from src.storage.db import get_session
            from src.storage.vectors import reindex_all

            with console.status("[bold green]Reindexing..."):
                async with get_session() as session:
                    counts = await reindex_all(session)

            console.print("\n[bold green]Reindex complete![/bold green]")
            for col, count in counts.items():
                console.print(f"  {col}: {count}")
        except ImportError:
            console.print("[red]chromadb not installed. Run: pip install chromadb[/red]")

    asyncio.run(_reindex())


@app.command()
def capture(
    project: Optional[str] = typer.Option(None, "--project", "-p", help="Specific project directory to scan"),
    no_extract: bool = typer.Option(False, "--no-extract", help="Skip decision extraction (just archive sessions)"),
    verbose: bool = typer.Option(False, "--verbose", "-v"),
):
    """Capture decisions from Claude Code sessions."""
    _setup_logging(verbose)

    async def _capture():
        from src.ingestion.claude_code import scan_sessions
        from src.storage.db import get_session

        with console.status("[bold green]Scanning Claude Code sessions..."):
            async with get_session() as session:
                summary = await scan_sessions(
                    session,
                    project_dir=project,
                    extract=not no_extract,
                )

        console.print("\n[bold green]Capture complete![/bold green]")
        console.print(f"  Sessions found:    {summary['sessions_found']}")
        console.print(f"  Sessions ingested: {summary['sessions_ingested']}")
        console.print(f"  Sessions skipped:  {summary['sessions_skipped']}")
        console.print(f"  Decisions found:   {summary['total_decisions']}")

    asyncio.run(_capture())


@app.command()
def reprocess(
    since: str = typer.Option(None, "--since", help="Reprocess since date (YYYY-MM-DD)"),
    extraction_version: str = typer.Option(None, "--extraction-version", help="Only reprocess this version"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Show what would change without writing"),
    limit: int = typer.Option(100, "--limit", help="Max items to reprocess"),
    verbose: bool = typer.Option(False, "--verbose", "-v"),
):
    """Re-extract raw data with current models."""
    _setup_logging(verbose)

    async def _reprocess():
        from datetime import datetime

        from src.storage.db import get_session
        from src.storage.raw import get_unprocessed_interactions, mark_processed

        since_dt = None
        if since:
            since_dt = datetime.fromisoformat(since)

        async with get_session() as session:
            interactions = await get_unprocessed_interactions(
                session,
                since=since_dt,
                extraction_version=extraction_version,
                limit=limit,
            )

            console.print(f"\nFound {len(interactions)} interactions to reprocess")

            if dry_run:
                for i in interactions[:10]:
                    console.print(f"  [{i.source_type}] {i.source_id} — {i.interaction_date or 'no date'}")
                if len(interactions) > 10:
                    console.print(f"  ... and {len(interactions) - 10} more")
                return

            processed = 0
            for interaction in interactions:
                # Re-run through pipeline based on source type
                if interaction.source_type == "email":
                    console.print(f"  Reprocessing {interaction.source_id}...")
                    processed += 1

            console.print(f"\n[green]Reprocessed {processed} interactions[/green]")

    asyncio.run(_reprocess())


@app.command("reset-processing")
def reset_processing(
    verbose: bool = typer.Option(False, "--verbose", "-v"),
):
    """Clear all classification/extraction results so emails get reprocessed on next sync."""
    _setup_logging(verbose)

    async def _reset():
        from sqlalchemy import update

        from src.storage.db import get_session
        from src.storage.models import Email

        async with get_session() as session:
            result = await session.execute(
                update(Email)
                .where(Email.classification.isnot(None))
                .values(
                    classification=None,
                    urgency=None,
                    needs_reply=False,
                    reply_suggested=None,
                    extraction_result=None,
                    processed_at=None,
                    sender_id=None,
                )
            )
            count = result.rowcount
            console.print(f"  Reset {count} emails — they will be reclassified on next [cyan]focus sync[/cyan]")

    asyncio.run(_reset())


def main():
    """Entry point for the focus CLI."""
    app()


if __name__ == "__main__":
    main()

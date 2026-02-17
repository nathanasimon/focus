"""CLI commands for managing projects."""

import asyncio
from datetime import date
from typing import Optional

import typer
from rich.console import Console
from rich.table import Table

app = typer.Typer(no_args_is_help=True)
console = Console()


@app.command("list")
def list_projects(
    status: Optional[str] = typer.Option(None, "--status", "-s", help="Filter by status"),
    tier: Optional[str] = typer.Option(None, "--tier", "-t", help="Filter by tier"),
):
    """List all projects."""

    async def _list():
        from sqlalchemy import select

        from src.context.project_state import get_active_project
        from src.storage.db import get_session
        from src.storage.models import Project

        active_slug = get_active_project()

        async with get_session() as session:
            query = select(Project).order_by(Project.last_activity.desc().nullslast())
            if status:
                query = query.where(Project.status == status)
            if tier:
                query = query.where(Project.tier == tier)

            result = await session.execute(query)
            projects = result.scalars().all()

            if not projects:
                console.print("[yellow]No projects found.[/yellow]")
                return

            table = Table(title="Projects")
            table.add_column("", width=2)
            table.add_column("Name", style="cyan")
            table.add_column("Slug")
            table.add_column("Tier")
            table.add_column("Status")
            table.add_column("Priority")
            table.add_column("Deadline")
            table.add_column("Pinned", justify="center")

            for p in projects:
                marker = "[green]>[/green]" if p.slug == active_slug else ""
                pinned = "[green]YES[/green]" if p.user_pinned else ""
                priority = p.user_priority or ""
                deadline = str(p.user_deadline) if p.user_deadline else ""
                table.add_row(marker, p.name, p.slug, p.tier, p.status, priority, deadline, pinned)

            console.print(table)

    asyncio.run(_list())


@app.command("pin")
def pin_project(slug: str = typer.Argument(help="Project slug to pin")):
    """Pin a project (always show prominently)."""

    async def _pin():
        from sqlalchemy import select, update

        from src.storage.db import get_session
        from src.storage.models import Project

        async with get_session() as session:
            result = await session.execute(select(Project).where(Project.slug == slug))
            project = result.scalar_one_or_none()
            if not project:
                console.print(f"[red]Project not found: {slug}[/red]")
                raise typer.Exit(1)

            project.user_pinned = True
            await session.flush()
            console.print(f"Project [cyan]{project.name}[/cyan] pinned")

    asyncio.run(_pin())


@app.command("unpin")
def unpin_project(slug: str = typer.Argument(help="Project slug to unpin")):
    """Unpin a project."""

    async def _unpin():
        from sqlalchemy import select

        from src.storage.db import get_session
        from src.storage.models import Project

        async with get_session() as session:
            result = await session.execute(select(Project).where(Project.slug == slug))
            project = result.scalar_one_or_none()
            if not project:
                console.print(f"[red]Project not found: {slug}[/red]")
                raise typer.Exit(1)

            project.user_pinned = False
            await session.flush()
            console.print(f"Project [cyan]{project.name}[/cyan] unpinned")

    asyncio.run(_unpin())


@app.command("priority")
def set_priority(
    slug: str = typer.Argument(help="Project slug"),
    priority: str = typer.Argument(help="Priority level: critical, high, normal, low"),
):
    """Set priority for a project."""
    valid = {"critical", "high", "normal", "low"}
    if priority not in valid:
        console.print(f"[red]Invalid priority. Choose from: {', '.join(valid)}[/red]")
        raise typer.Exit(1)

    async def _set():
        from sqlalchemy import select

        from src.storage.db import get_session
        from src.storage.models import Project

        async with get_session() as session:
            result = await session.execute(select(Project).where(Project.slug == slug))
            project = result.scalar_one_or_none()
            if not project:
                console.print(f"[red]Project not found: {slug}[/red]")
                raise typer.Exit(1)

            project.user_priority = priority
            await session.flush()
            console.print(f"Project [cyan]{project.name}[/cyan] priority set to [bold]{priority}[/bold]")

    asyncio.run(_set())


@app.command("deadline")
def set_deadline(
    slug: str = typer.Argument(help="Project slug"),
    deadline_str: str = typer.Argument(help="Deadline date (YYYY-MM-DD)"),
    note: Optional[str] = typer.Option(None, "--note", "-n", help="Why this deadline matters"),
):
    """Set a deadline for a project."""

    async def _set():
        from sqlalchemy import select

        from src.storage.db import get_session
        from src.storage.models import Project

        try:
            deadline = date.fromisoformat(deadline_str)
        except ValueError:
            console.print("[red]Invalid date format. Use YYYY-MM-DD[/red]")
            raise typer.Exit(1)

        async with get_session() as session:
            result = await session.execute(select(Project).where(Project.slug == slug))
            project = result.scalar_one_or_none()
            if not project:
                console.print(f"[red]Project not found: {slug}[/red]")
                raise typer.Exit(1)

            project.user_deadline = deadline
            if note:
                project.user_deadline_note = note
            await session.flush()

            note_str = f" ({note})" if note else ""
            console.print(f"Project [cyan]{project.name}[/cyan] deadline set to [bold]{deadline}{note_str}[/bold]")

    asyncio.run(_set())


@app.command("use")
def use_project(
    slug: str = typer.Argument(help="Project slug to set as active"),
    workspace: Optional[str] = typer.Option(None, "--workspace", "-w", help="Workspace path (defaults to cwd)"),
    set_global: bool = typer.Option(False, "--global", "-g", help="Set as global default (not per-workspace)"),
):
    """Set the active project for context injection."""
    import os

    from src.context.project_state import set_active_project

    if set_global:
        set_active_project(slug)
        console.print(f"Active project set globally: [cyan]{slug}[/cyan]")
    else:
        ws = workspace or os.getcwd()
        set_active_project(slug, workspace=ws)
        console.print(f"Active project set: [cyan]{slug}[/cyan] (workspace: {ws})")


@app.command("unuse")
def unuse_project(
    workspace: Optional[str] = typer.Option(None, "--workspace", "-w", help="Workspace path (defaults to cwd)"),
    clear_global: bool = typer.Option(False, "--global", "-g", help="Clear global default"),
):
    """Clear the active project selection."""
    import os

    from src.context.project_state import clear_active_project

    if clear_global:
        clear_active_project()
        console.print("Global active project cleared")
    else:
        ws = workspace or os.getcwd()
        clear_active_project(workspace=ws)
        console.print(f"Active project cleared for workspace: {ws}")


@app.command("sessions")
def list_sessions(
    slug: str = typer.Argument(help="Project slug"),
    limit: int = typer.Option(20, "--limit", "-n", help="Max sessions to show"),
):
    """Show sessions linked to a project."""

    async def _list():
        from sqlalchemy import select
        from sqlalchemy.orm import selectinload

        from src.storage.db import get_session
        from src.storage.models import AgentSession, Project

        async with get_session() as session:
            project = (await session.execute(
                select(Project).where(Project.slug == slug)
            )).scalar_one_or_none()

            if not project:
                console.print(f"[red]Project not found: {slug}[/red]")
                raise typer.Exit(1)

            sessions = (await session.execute(
                select(AgentSession)
                .where(AgentSession.project_id == project.id)
                .order_by(AgentSession.last_activity_at.desc().nullslast())
                .limit(limit)
            )).scalars().all()

            if not sessions:
                console.print(f"[yellow]No sessions found for project: {slug}[/yellow]")
                return

            table = Table(title=f"Sessions — {project.name}")
            table.add_column("Session ID", style="dim")
            table.add_column("Title")
            table.add_column("Turns", justify="right")
            table.add_column("Last Activity")

            for s in sessions:
                sid = s.session_id[:12] + "..."
                title = s.session_title or "(untitled)"
                turns = str(s.turn_count)
                activity = str(s.last_activity_at)[:19] if s.last_activity_at else "—"
                table.add_row(sid, title, turns, activity)

            console.print(table)

    asyncio.run(_list())


@app.command("docs")
def generate_project_docs_cmd(
    slug: str = typer.Argument(help="Project slug"),
):
    """Generate/update documentation scaffold for a project."""

    async def _gen():
        from pathlib import Path

        from src.output.claude_md import generate_project_docs
        from src.storage.db import get_session

        docs_base = Path(__file__).resolve().parent.parent.parent / "docs"
        async with get_session() as session:
            await generate_project_docs(session, slug, docs_base)
        console.print(f"[green]Docs generated for {slug}[/green]")

    asyncio.run(_gen())


@app.command("create")
def create_project(
    name: str = typer.Argument(help="Project name"),
    description: str = typer.Option("", "--desc", "-d", help="Project description"),
    tier: str = typer.Option("simple", "--tier", "-t", help="Project tier"),
):
    """Create a new project manually."""

    async def _create():
        from src.processing.resolver import resolve_project
        from src.storage.db import get_session

        async with get_session() as session:
            project = await resolve_project(session, name=name, description=description or None)
            if tier in ("fleeting", "simple", "complex", "life_thread"):
                project.tier = tier
                await session.flush()
            console.print(f"Project [cyan]{project.name}[/cyan] created (slug: {project.slug})")

    asyncio.run(_create())

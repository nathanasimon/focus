"""CLI commands for managing sprints (time-bounded priority overrides)."""

import asyncio
from datetime import datetime, timezone
from typing import Optional

import typer
from rich.console import Console
from rich.table import Table

app = typer.Typer(no_args_is_help=True)
console = Console()


@app.command("create")
def create_sprint(
    name: str = typer.Argument(help="Sprint name (e.g., 'GRE Prep')"),
    project_slug: str = typer.Option(..., "--project", "-p", help="Project slug to boost"),
    until: str = typer.Option(..., "--until", "-u", help="End date (YYYY-MM-DD)"),
    boost: float = typer.Option(2.0, "--boost", "-b", help="Priority multiplier"),
    auto_archive: bool = typer.Option(True, "--auto-archive/--no-auto-archive", help="Archive project when sprint ends"),
    description: Optional[str] = typer.Option(None, "--desc", "-d", help="Sprint description"),
):
    """Create a new time-bounded sprint."""

    async def _create():
        from sqlalchemy import select

        from src.storage.db import get_session
        from src.storage.models import Project, Sprint

        try:
            ends_at = datetime.fromisoformat(until)
        except ValueError:
            console.print("[red]Invalid date format. Use YYYY-MM-DD[/red]")
            raise typer.Exit(1)

        async with get_session() as session:
            # Find project
            result = await session.execute(select(Project).where(Project.slug == project_slug))
            project = result.scalar_one_or_none()
            if not project:
                console.print(f"[red]Project not found: {project_slug}[/red]")
                raise typer.Exit(1)

            sprint = Sprint(
                name=name,
                description=description,
                project_id=project.id,
                priority_boost=boost,
                starts_at=datetime.now(timezone.utc),
                ends_at=ends_at,
                auto_archive_project=auto_archive,
            )
            session.add(sprint)
            await session.flush()

            days = (ends_at.date() - datetime.now(timezone.utc).date()).days
            console.print(f"Sprint [bold]{name}[/bold] created")
            console.print(f"  Project: {project.name}")
            console.print(f"  Boost: {boost}x")
            console.print(f"  Ends: {until} ({days} days)")
            if auto_archive:
                console.print(f"  Auto-archive: ON (project will be archived when sprint ends)")

    asyncio.run(_create())


@app.command("list")
def list_sprints(
    all_sprints: bool = typer.Option(False, "--all", "-a", help="Show inactive sprints too"),
):
    """Show sprints."""

    async def _list():
        from sqlalchemy import select

        from src.storage.db import get_session
        from src.storage.models import Project, Sprint

        async with get_session() as session:
            query = select(Sprint, Project).outerjoin(Project, Sprint.project_id == Project.id)
            if not all_sprints:
                query = query.where(Sprint.is_active.is_(True))
            query = query.order_by(Sprint.ends_at.asc())

            result = await session.execute(query)
            rows = result.all()

            if not rows:
                console.print("[yellow]No active sprints.[/yellow]")
                return

            table = Table(title="Sprints")
            table.add_column("Name", style="cyan")
            table.add_column("Project")
            table.add_column("Boost", justify="right")
            table.add_column("Ends")
            table.add_column("Days Left", justify="right")
            table.add_column("Active", justify="center")

            for sprint, project in rows:
                project_name = project.name if project else "—"
                ends = sprint.ends_at.strftime("%Y-%m-%d")
                days_left = max(0, (sprint.ends_at.date() - datetime.now(timezone.utc).date()).days)
                active = "[green]YES[/green]" if sprint.is_active else "[red]NO[/red]"
                table.add_row(
                    sprint.name,
                    project_name,
                    f"{sprint.priority_boost:.1f}x",
                    ends,
                    str(days_left),
                    active,
                )

            console.print(table)

    asyncio.run(_list())


@app.command("deactivate")
def deactivate_sprint(name: str = typer.Argument(help="Sprint name to deactivate")):
    """End a sprint early."""

    async def _deactivate():
        from sqlalchemy import select

        from src.storage.db import get_session
        from src.storage.models import Sprint

        async with get_session() as session:
            result = await session.execute(
                select(Sprint).where(Sprint.name == name, Sprint.is_active.is_(True))
            )
            sprint = result.scalar_one_or_none()
            if not sprint:
                console.print(f"[red]Active sprint not found: {name}[/red]")
                raise typer.Exit(1)

            sprint.is_active = False
            await session.flush()
            console.print(f"Sprint [cyan]{name}[/cyan] deactivated")

    asyncio.run(_deactivate())

"""CLI commands for managing tasks."""

import asyncio
from datetime import date
from typing import Optional

import typer
from rich.console import Console
from rich.table import Table

app = typer.Typer(no_args_is_help=True)
console = Console()


@app.command("create")
def create_task(
    title: str = typer.Argument(help="Task title"),
    project: Optional[str] = typer.Option(None, "--project", "-p", help="Project slug to link to"),
    due: Optional[str] = typer.Option(None, "--due", "-d", help="Due date (YYYY-MM-DD)"),
    priority: str = typer.Option("normal", "--priority", help="Priority: urgent, high, normal, low"),
):
    """Create a new task manually."""

    async def _create():
        from sqlalchemy import select

        from src.storage.db import get_session
        from src.storage.models import Project, Task

        async with get_session() as session:
            project_id = None
            if project:
                result = await session.execute(select(Project).where(Project.slug == project))
                proj = result.scalar_one_or_none()
                if proj:
                    project_id = proj.id
                else:
                    console.print(f"[yellow]Project '{project}' not found, creating task without project link[/yellow]")

            task = Task(
                title=title,
                project_id=project_id,
                priority=priority,
                source_type="user",
            )

            if due:
                try:
                    task.due_date = date.fromisoformat(due)
                except ValueError:
                    console.print("[red]Invalid date format. Use YYYY-MM-DD[/red]")
                    raise typer.Exit(1)

            session.add(task)
            await session.flush()
            console.print(f"Task created: [cyan]{title}[/cyan] (id: {str(task.id)[:8]})")

    asyncio.run(_create())


@app.command("list")
def list_tasks(
    project: Optional[str] = typer.Option(None, "--project", "-p", help="Filter by project slug"),
    status: Optional[str] = typer.Option(None, "--status", "-s", help="Filter by status"),
):
    """List tasks."""

    async def _list():
        from sqlalchemy import select

        from src.storage.db import get_session
        from src.storage.models import Project, Task

        async with get_session() as session:
            query = select(Task).order_by(Task.created_at.desc())

            if project:
                result = await session.execute(select(Project.id).where(Project.slug == project))
                proj_id = result.scalar_one_or_none()
                if proj_id:
                    query = query.where(Task.project_id == proj_id)

            if status:
                query = query.where(Task.status == status)

            result = await session.execute(query.limit(50))
            tasks = result.scalars().all()

            if not tasks:
                console.print("[yellow]No tasks found.[/yellow]")
                return

            table = Table(title="Tasks")
            table.add_column("ID", style="dim")
            table.add_column("Title", style="cyan")
            table.add_column("Status")
            table.add_column("Priority")
            table.add_column("Due")
            table.add_column("Pinned", justify="center")

            for t in tasks:
                pinned = "[green]YES[/green]" if t.user_pinned else ""
                due = str(t.due_date) if t.due_date else ""
                table.add_row(
                    str(t.id)[:8],
                    t.title,
                    t.status,
                    t.user_priority or t.priority,
                    due,
                    pinned,
                )

            console.print(table)

    asyncio.run(_list())


@app.command("priority")
def set_priority(
    task_id: str = typer.Argument(help="Task ID (first 8 chars is enough)"),
    priority: str = typer.Argument(help="Priority: urgent, high, normal, low"),
):
    """Set priority for a task."""
    valid = {"urgent", "high", "normal", "low"}
    if priority not in valid:
        console.print(f"[red]Invalid priority. Choose from: {', '.join(valid)}[/red]")
        raise typer.Exit(1)

    async def _set():
        from sqlalchemy import select

        from src.storage.db import get_session
        from src.storage.models import Task

        async with get_session() as session:
            result = await session.execute(
                select(Task).where(Task.id.cast(str).like(f"{task_id}%"))
            )
            task = result.scalar_one_or_none()
            if not task:
                console.print(f"[red]Task not found: {task_id}[/red]")
                raise typer.Exit(1)

            task.user_priority = priority
            await session.flush()
            console.print(f"Task [cyan]{task.title}[/cyan] priority set to [bold]{priority}[/bold]")

    asyncio.run(_set())


@app.command("done")
def mark_done(task_id: str = typer.Argument(help="Task ID")):
    """Mark a task as done."""

    async def _done():
        from datetime import datetime, timezone

        from sqlalchemy import select

        from src.storage.db import get_session
        from src.storage.models import Task

        async with get_session() as session:
            result = await session.execute(
                select(Task).where(Task.id.cast(str).like(f"{task_id}%"))
            )
            task = result.scalar_one_or_none()
            if not task:
                console.print(f"[red]Task not found: {task_id}[/red]")
                raise typer.Exit(1)

            task.status = "done"
            task.completed_at = datetime.now(timezone.utc)
            await session.flush()
            console.print(f"Task [cyan]{task.title}[/cyan] marked as [green]done[/green]")

    asyncio.run(_done())


@app.command("deadline")
def set_deadline(
    task_id: str = typer.Argument(help="Task ID"),
    deadline_str: str = typer.Argument(help="Due date (YYYY-MM-DD)"),
):
    """Set a deadline for a task."""

    async def _set():
        from sqlalchemy import select

        from src.storage.db import get_session
        from src.storage.models import Task

        try:
            deadline = date.fromisoformat(deadline_str)
        except ValueError:
            console.print("[red]Invalid date format. Use YYYY-MM-DD[/red]")
            raise typer.Exit(1)

        async with get_session() as session:
            result = await session.execute(
                select(Task).where(Task.id.cast(str).like(f"{task_id}%"))
            )
            task = result.scalar_one_or_none()
            if not task:
                console.print(f"[red]Task not found: {task_id}[/red]")
                raise typer.Exit(1)

            task.due_date = deadline
            await session.flush()
            console.print(f"Task [cyan]{task.title}[/cyan] deadline set to [bold]{deadline}[/bold]")

    asyncio.run(_set())

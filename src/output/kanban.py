"""Per-project Kanban board generation."""

import logging
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.storage.models import Person, Project, Task

logger = logging.getLogger(__name__)


async def generate_kanban(
    session: AsyncSession,
    project: Project,
    output_dir: Path,
) -> None:
    """Generate KANBAN.md for a project."""
    result = await session.execute(
        select(Task)
        .where(Task.project_id == project.id)
        .order_by(Task.created_at.asc())
    )
    tasks = result.scalars().all()

    backlog = [t for t in tasks if t.status == "backlog"]
    in_progress = [t for t in tasks if t.status == "in_progress"]
    waiting = [t for t in tasks if t.status == "waiting"]
    done = [t for t in tasks if t.status == "done"]

    # Only show recent done items (last 2 weeks)
    cutoff = datetime.now(timezone.utc).timestamp() - (14 * 86400)
    recent_done = [
        t for t in done
        if t.completed_at and t.completed_at.timestamp() > cutoff
    ]

    lines = [f"# Tasks: {project.name}", ""]

    # Backlog
    lines.append("## Backlog")
    if backlog:
        for task in backlog:
            lines.append(_format_task(task))
    else:
        lines.append("_Empty_")
    lines.append("")

    # In Progress
    lines.append("## In Progress")
    if in_progress:
        for task in in_progress:
            started = ""
            if task.created_at:
                started = f" — Started: {task.created_at.strftime('%Y-%m-%d')}"
            lines.append(f"{_format_task(task)}{started}")
    else:
        lines.append("_Nothing in progress_")
    lines.append("")

    # Waiting On
    lines.append("## Waiting On")
    if waiting:
        for task in waiting:
            wait_info = ""
            if task.waiting_since:
                days = (datetime.now(timezone.utc) - task.waiting_since).days
                wait_info = f" | Days waiting: {days}"
                if days > 3:
                    wait_info += " | **Suggested**: Follow up"
            lines.append(f"{_format_task(task)}{wait_info}")
    else:
        lines.append("_Nothing waiting_")
    lines.append("")

    # Done (recent)
    lines.append("## Done (Recent)")
    if recent_done:
        for task in recent_done:
            done_date = task.completed_at.strftime("%Y-%m-%d") if task.completed_at else "?"
            lines.append(f"- [x] {task.title} — done {done_date}")
    else:
        lines.append("_No recent completions_")

    (output_dir / "KANBAN.md").write_text("\n".join(lines) + "\n")


def _format_task(task: Task) -> str:
    """Format a single task as a markdown checkbox line."""
    parts = [f"- [ ] {task.title}"]

    tags = []
    if task.priority in ("urgent", "high"):
        tags.append(f"#{task.priority}")
    if task.source_type:
        tags.append(f"#{task.source_type}")

    if tags:
        parts.append(" ".join(tags))

    if task.due_date:
        parts.append(f"due: {task.due_date}")

    if task.user_pinned:
        parts.append("PINNED")

    return " ".join(parts)

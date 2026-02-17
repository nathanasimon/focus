"""CLI commands for viewing priority rankings."""

import asyncio
from typing import Optional

import typer
from rich.console import Console
from rich.table import Table

app = typer.Typer(invoke_without_command=True)
console = Console()


@app.callback(invoke_without_command=True)
def priorities(
    week: bool = typer.Option(False, "--week", help="Show only this week's priorities"),
    today: bool = typer.Option(False, "--today", help="Show only today's priorities"),
):
    """Show effective priority ranking of all active projects."""

    async def _priorities():
        from src.priority import get_priority_ranking
        from src.storage.db import get_session

        scope = "all"
        if today:
            scope = "today"
        elif week:
            scope = "week"

        async with get_session() as session:
            ranked = await get_priority_ranking(session, scope=scope)

            if not ranked:
                console.print("[yellow]No projects to rank.[/yellow]")
                return

            scope_label = {"all": "All Projects", "today": "Today", "week": "This Week"}[scope]
            table = Table(title=f"Priority Ranking — {scope_label}")
            table.add_column("#", style="dim", justify="right")
            table.add_column("Project", style="cyan")
            table.add_column("Score", justify="right")
            table.add_column("Priority")
            table.add_column("Deadline")
            table.add_column("Pinned", justify="center")

            for i, item in enumerate(ranked, 1):
                pinned = "[green]YES[/green]" if item["pinned"] else ""
                priority = item["priority"] or ""
                deadline = str(item["deadline"]) if item["deadline"] else ""
                table.add_row(
                    str(i),
                    item["name"],
                    f"{item['score']:.1f}",
                    priority,
                    deadline,
                    pinned,
                )

            console.print(table)

    asyncio.run(_priorities())

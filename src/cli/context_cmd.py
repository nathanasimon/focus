"""CLI commands for context system management and debugging."""

import asyncio
import logging
from typing import Optional

import typer
from rich.console import Console
from rich.table import Table

logger = logging.getLogger(__name__)
console = Console()

app = typer.Typer(no_args_is_help=True)


@app.command("query")
def context_query(
    query: str = typer.Argument(help="Query to test context retrieval"),
    cwd: Optional[str] = typer.Option(None, "--cwd", help="Simulate working directory"),
    max_tokens: int = typer.Option(1500, "--tokens"),
    verbose: bool = typer.Option(False, "--verbose", "-v"),
):
    """Preview what context would be injected for a given query."""
    if verbose:
        logging.basicConfig(level=logging.DEBUG)

    async def _run():
        from src.context.classifier import PromptClassifier
        from src.context.formatter import format_context_blocks
        from src.context.retriever import ContextRetriever
        from src.storage.db import get_session

        async with get_session() as session:
            classifier = PromptClassifier()
            await classifier.load_entities(session)

            classification = classifier.classify(query, cwd)

            console.print(f"\n[bold]Classification:[/bold]")
            console.print(f"  Projects:   {classification.project_slugs or '(none)'}")
            console.print(f"  People:     {classification.person_names or '(none)'}")
            console.print(f"  Type:       {classification.query_type}")
            console.print(f"  Workspace:  {classification.workspace_project or '(none)'}")
            console.print(f"  Confidence: {classification.confidence:.1%}")

            retriever = ContextRetriever()
            blocks = await retriever.retrieve(session, classification, max_tokens=max_tokens)

            formatted = format_context_blocks(blocks, max_tokens=max_tokens)
            if formatted:
                console.print(f"\n[bold]Would inject ({len(formatted)} chars, ~{len(formatted)//4} tokens):[/bold]\n")
                console.print(formatted)
            else:
                console.print("\n[yellow]No context to inject.[/yellow]")

    asyncio.run(_run())


@app.command("show")
def context_show(
    verbose: bool = typer.Option(False, "--verbose", "-v"),
):
    """Show current project detection and context state."""
    if verbose:
        logging.basicConfig(level=logging.DEBUG)

    import os

    from src.context.classifier import PromptClassifier

    async def _run():
        from src.storage.db import get_session

        cwd = os.getcwd()

        async with get_session() as session:
            classifier = PromptClassifier()
            await classifier.load_entities(session)

            # Classify with empty prompt to just get workspace detection
            classification = classifier.classify("", cwd)

            console.print(f"\n[bold]Context State:[/bold]")
            console.print(f"  CWD:              {cwd}")
            console.print(f"  Workspace project: {classification.workspace_project or '(none detected)'}")
            console.print(f"  Known projects:    {len(classifier._projects)}")
            console.print(f"  Known people:      {len(classifier._people)}")

    asyncio.run(_run())


@app.command("stats")
def context_stats(
    verbose: bool = typer.Option(False, "--verbose", "-v"),
):
    """Show recording statistics (sessions, turns, jobs, etc.)."""
    if verbose:
        logging.basicConfig(level=logging.DEBUG)

    async def _run():
        from sqlalchemy import func, select

        from src.storage.db import get_session
        from src.storage.jobs import get_job_stats
        from src.storage.models import AgentSession, AgentTurn, AgentTurnEntity

        async with get_session() as session:
            # Session counts
            total_sessions = (await session.execute(
                select(func.count()).select_from(AgentSession)
            )).scalar()

            processed_sessions = (await session.execute(
                select(func.count()).select_from(AgentSession)
                .where(AgentSession.is_processed.is_(True))
            )).scalar()

            # Turn counts
            total_turns = (await session.execute(
                select(func.count()).select_from(AgentTurn)
            )).scalar()

            summarized_turns = (await session.execute(
                select(func.count()).select_from(AgentTurn)
                .where(AgentTurn.assistant_summary.isnot(None))
            )).scalar()

            # Entity counts
            total_entities = (await session.execute(
                select(func.count()).select_from(AgentTurnEntity)
            )).scalar()

            # Job stats
            job_stats = await get_job_stats(session)

        console.print("\n[bold]Context System Stats[/bold]\n")

        table = Table()
        table.add_column("Metric", style="cyan")
        table.add_column("Count", style="green", justify="right")

        table.add_row("Sessions (total)", str(total_sessions))
        table.add_row("Sessions (processed)", str(processed_sessions))
        table.add_row("Turns (total)", str(total_turns))
        table.add_row("Turns (summarized)", str(summarized_turns))
        table.add_row("Entity links", str(total_entities))

        console.print(table)

        if job_stats:
            console.print("\n[bold]Job Queue:[/bold]")
            for status, count in sorted(job_stats.items()):
                style = "red" if status == "failed" else "green" if status == "done" else "yellow"
                console.print(f"  [{style}]{status}: {count}[/{style}]")
        else:
            console.print("\n[dim]No jobs in queue.[/dim]")

    asyncio.run(_run())

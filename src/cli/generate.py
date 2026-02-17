"""CLI commands for regenerating output files."""

import asyncio
from typing import Optional

import typer
from rich.console import Console

app = typer.Typer(invoke_without_command=True)
console = Console()


@app.callback(invoke_without_command=True)
def generate(
    vault_only: bool = typer.Option(False, "--vault-only", help="Only regenerate vault, skip CLAUDE.md"),
    claude_only: bool = typer.Option(False, "--claude-only", help="Only regenerate CLAUDE.md"),
    project: Optional[str] = typer.Option(None, "--project", "-p", help="Project slug for CLAUDE.md"),
    docs: bool = typer.Option(False, "--docs", help="Also regenerate reference docs"),
):
    """Regenerate all markdown outputs (vault + CLAUDE.md)."""

    async def _generate():
        from src.output.claude_md import generate_claude_md
        from src.output.vault import generate_vault
        from src.storage.db import get_session

        async with get_session() as session:
            if not claude_only:
                with console.status("[bold green]Generating vault..."):
                    await generate_vault(session)
                console.print("[green]Vault generated[/green]")

            if not vault_only:
                with console.status("[bold green]Generating CLAUDE.md..."):
                    await generate_claude_md(session, project_slug=project, generate_docs=docs)
                console.print("[green]CLAUDE.md generated[/green]")

        console.print("\n[bold green]Generation complete![/bold green]")

    asyncio.run(_generate())

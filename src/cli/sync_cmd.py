"""CLI commands for syncing data from sources."""

import asyncio
from typing import Optional

import typer
from rich.console import Console

app = typer.Typer(invoke_without_command=True)
console = Console()


@app.callback(invoke_without_command=True)
def sync(
    account: Optional[str] = typer.Option(None, "--account", "-a", help="Sync specific account only"),
    full: bool = typer.Option(False, "--full", help="Full sync (ignore cursor, re-fetch all)"),
    process: bool = typer.Option(True, "--process/--no-process", help="Process emails after syncing"),
    limit: int = typer.Option(0, "--limit", help="Max emails to process (0 = all)"),
    verbose: bool = typer.Option(False, "--verbose", "-v"),
):
    """Pull new data from all sources and process it."""

    async def _sync():
        from src.config import get_settings
        from src.ingestion.pipeline import process_unprocessed_emails, run_full_sync
        from src.output.claude_md import generate_claude_md
        from src.output.vault import generate_vault
        from src.priority import expire_sprints
        from src.storage.db import get_session

        settings = get_settings()

        with console.status("[bold green]Syncing...") as status:
            async with get_session() as session:
                # Expire old sprints
                expired = await expire_sprints(session)
                if expired:
                    console.print(f"  Expired sprints: {', '.join(expired)}")

                # Sync emails
                status.update("[bold green]Fetching emails...")
                sync_summary = await run_full_sync(session, account)
                drive_msg = ""
                if sync_summary.get("drive_files_synced", 0) > 0:
                    drive_msg = f", {sync_summary['drive_files_synced']} Drive files"
                console.print(
                    f"  Synced {sync_summary['accounts']} account(s), "
                    f"{sync_summary['emails_fetched']} new emails{drive_msg}"
                )

                # Process any unclassified emails (new or left over from prior runs)
                if process:
                    status.update("[bold green]Processing emails...")
                    proc_summary = await process_unprocessed_emails(session, limit=limit)
                    total = sum(proc_summary[k] for k in ("classified", "deep_extracted", "regex_parsed", "skipped", "errors"))
                    if total > 0:
                        errors_msg = ""
                        if proc_summary.get("errors", 0) > 0:
                            errors_msg = f", Errors: {proc_summary['errors']}"
                        console.print(
                            f"  Classified: {proc_summary['classified']}, "
                            f"Extracted: {proc_summary['deep_extracted']}, "
                            f"Parsed: {proc_summary['regex_parsed']}, "
                            f"Skipped: {proc_summary['skipped']}{errors_msg}"
                        )

                # Regenerate vault and CLAUDE.md
                if settings.vault.auto_regenerate:
                    status.update("[bold green]Generating vault...")
                    await generate_vault(session)
                    await generate_claude_md(session)
                    console.print("  Vault and CLAUDE.md regenerated")

        console.print("\n[bold green]Sync complete![/bold green]")

    asyncio.run(_sync())

"""Focus daemon — continuous background sync and vault regeneration."""

import asyncio
import logging
import signal
from datetime import datetime, timezone

from rich.console import Console

from src.config import get_settings
from src.ingestion.pipeline import process_unprocessed_emails, run_full_sync
from src.output.claude_md import generate_claude_md
from src.output.vault import generate_vault
from src.priority import expire_sprints
from src.storage.db import close_db, get_session

logger = logging.getLogger(__name__)
console = Console()

_running = True


def _handle_shutdown(signum, frame):
    global _running
    _running = False
    logger.info("Shutdown signal received, finishing current cycle...")


async def run_daemon(interval_minutes: int = 15) -> None:
    """Run the Focus daemon — sync and regenerate on interval.

    Args:
        interval_minutes: Minutes between sync cycles.
    """
    global _running

    signal.signal(signal.SIGINT, _handle_shutdown)
    signal.signal(signal.SIGTERM, _handle_shutdown)

    settings = get_settings()
    interval = interval_minutes * 60

    console.print(f"[bold]Focus daemon started[/bold] (interval: {interval_minutes}m)")
    console.print("Press Ctrl+C to stop.\n")

    cycle = 0
    while _running:
        cycle += 1
        start = datetime.now(timezone.utc)
        logger.info("Daemon cycle %d starting at %s", cycle, start.isoformat())

        try:
            async with get_session() as session:
                # 1. Expire old sprints
                expired = await expire_sprints(session)
                if expired:
                    logger.info("Expired sprints: %s", ", ".join(expired))

                # 2. Sync all accounts
                sync_summary = await run_full_sync(session)
                logger.info(
                    "Sync: %d accounts, %d new emails, %d Drive files",
                    sync_summary["accounts"],
                    sync_summary["emails_fetched"],
                    sync_summary.get("drive_files_synced", 0),
                )

                # 3. Process unprocessed emails
                if sync_summary["emails_fetched"] > 0:
                    proc_summary = await process_unprocessed_emails(session, limit=100)
                    logger.info(
                        "Processing: classified=%d, extracted=%d, parsed=%d",
                        proc_summary["classified"],
                        proc_summary["deep_extracted"],
                        proc_summary["regex_parsed"],
                    )

                # 4. Scan Claude Code sessions
                try:
                    from src.ingestion.claude_code import scan_sessions

                    capture_summary = await scan_sessions(session, extract=True)
                    if capture_summary["sessions_ingested"] > 0:
                        logger.info(
                            "Captured %d Claude Code sessions (%d decisions)",
                            capture_summary["sessions_ingested"],
                            capture_summary["total_decisions"],
                        )
                except Exception as e:
                    logger.debug("Claude Code capture skipped: %s", e)

            # 4.5. Process context worker jobs (outside main session)
            try:
                from src.context.worker import process_pending_jobs

                jobs_processed = await process_pending_jobs(max_jobs=20)
                if jobs_processed > 0:
                    logger.info("Processed %d context jobs", jobs_processed)
            except Exception as e:
                logger.debug("Context job processing skipped: %s", e)

            async with get_session() as session:
                # 5. Regenerate vault and CLAUDE.md
                if settings.vault.auto_regenerate:
                    await generate_vault(session)
                    await generate_claude_md(session)
                    logger.info("Vault and CLAUDE.md regenerated")

            elapsed = (datetime.now(timezone.utc) - start).total_seconds()
            logger.info("Cycle %d complete in %.1fs", cycle, elapsed)

        except Exception as e:
            logger.error("Daemon cycle %d failed: %s", cycle, e, exc_info=True)

        # Wait for next cycle
        if _running:
            logger.info("Next sync in %d minutes...", interval_minutes)
            try:
                await asyncio.sleep(interval)
            except asyncio.CancelledError:
                break

    await close_db()
    console.print("\n[bold]Focus daemon stopped.[/bold]")

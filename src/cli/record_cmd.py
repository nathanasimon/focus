"""CLI command for recording Claude Code conversations."""

import asyncio
import json
import logging
import sys
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console

logger = logging.getLogger(__name__)
console = Console()

app = typer.Typer(invoke_without_command=True)


@app.callback(invoke_without_command=True)
def record(
    hook: bool = typer.Option(False, "--hook", help="Read stdin JSON (Claude Code hook mode)"),
    hook_async: bool = typer.Option(False, "--async", help="Enqueue only, don't process inline"),
    all_sessions: bool = typer.Option(False, "--all", help="Scan and record all unprocessed sessions"),
    verbose: bool = typer.Option(False, "--verbose", "-v"),
):
    """Record Claude Code conversations."""
    if hook:
        _hook_record()
    elif all_sessions:
        _record_all(verbose)
    else:
        console.print("Usage: focus record --hook (for Claude Code) or --all (scan all sessions)")


def _hook_record():
    """Fast synchronous path for --hook mode.

    Reads stdin JSON from Claude Code Stop hook, enqueues a recording
    job, and exits. Target: <200ms.
    """
    try:
        input_data = json.loads(sys.stdin.read())
    except (json.JSONDecodeError, ValueError):
        sys.exit(0)

    session_id = input_data.get("session_id", "")
    transcript_path = input_data.get("transcript_path", "")
    cwd = input_data.get("cwd", "")

    if not session_id or not transcript_path:
        sys.exit(0)

    async def _enqueue():
        from src.context.recorder import enqueue_session_recording

        await enqueue_session_recording(session_id, transcript_path, cwd)

    try:
        asyncio.run(_enqueue())
    except Exception:
        pass

    sys.exit(0)


def _record_all(verbose: bool):
    """Scan all Claude Code sessions and record unprocessed ones."""
    if verbose:
        logging.basicConfig(level=logging.DEBUG)

    async def _scan():
        from sqlalchemy import select

        from src.context.recorder import record_session
        from src.ingestion.claude_code import CLAUDE_SESSIONS_DIR
        from src.storage.db import get_session
        from src.storage.models import AgentSession

        base_dir = CLAUDE_SESSIONS_DIR
        if not base_dir.exists():
            console.print(f"[yellow]No sessions directory: {base_dir}[/yellow]")
            return

        # Collect all JSONL files
        jsonl_files = []
        for project_dir in base_dir.iterdir():
            if project_dir.is_dir():
                jsonl_files.extend(sorted(project_dir.glob("*.jsonl")))

        if not jsonl_files:
            console.print("[yellow]No session files found.[/yellow]")
            return

        console.print(f"Found {len(jsonl_files)} session files")

        recorded = 0
        skipped = 0
        errors = 0

        for jsonl_file in jsonl_files:
            session_id = jsonl_file.stem
            workspace_path = jsonl_file.parent.name

            try:
                async with get_session() as session:
                    result = await record_session(
                        session=session,
                        session_id=session_id,
                        transcript_path=str(jsonl_file),
                        workspace_path=workspace_path,
                    )
                    if result["turns_recorded"] > 0:
                        recorded += 1
                    else:
                        skipped += 1
            except Exception as e:
                logger.error("Failed to record %s: %s", session_id[:12], e)
                errors += 1

        console.print(f"\n[bold green]Recording complete![/bold green]")
        console.print(f"  Recorded: {recorded}")
        console.print(f"  Skipped:  {skipped}")
        if errors > 0:
            console.print(f"  [red]Errors:   {errors}[/red]")

    asyncio.run(_scan())

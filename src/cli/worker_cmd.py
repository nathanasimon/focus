"""CLI commands for managing the context worker."""

import asyncio
import logging
import os
import signal
from pathlib import Path

import typer
from rich.console import Console

logger = logging.getLogger(__name__)
console = Console()

app = typer.Typer(no_args_is_help=True)

PID_FILE = Path.home() / ".config" / "focus" / "worker.pid"


@app.command("start")
def start_worker(
    daemon_mode: bool = typer.Option(False, "--daemon", "-d", help="Run as background process"),
    poll_interval: float = typer.Option(2.0, "--interval", help="Poll interval in seconds"),
    verbose: bool = typer.Option(False, "--verbose", "-v"),
):
    """Start the Focus context worker."""
    if verbose:
        logging.basicConfig(level=logging.DEBUG)
    else:
        logging.basicConfig(level=logging.INFO)

    from src.context.worker import run_worker

    if daemon_mode:
        _start_daemon(poll_interval)
    else:
        console.print("[bold]Starting context worker[/bold] (Ctrl+C to stop)")
        asyncio.run(run_worker(poll_interval=poll_interval))


def _start_daemon(poll_interval: float):
    """Fork into a background daemon."""
    pid = os.fork()
    if pid > 0:
        # Parent process
        PID_FILE.parent.mkdir(parents=True, exist_ok=True)
        PID_FILE.write_text(str(pid))
        console.print(f"[green]Worker started[/green] (PID: {pid})")
        console.print(f"  PID file: {PID_FILE}")
        return

    # Child process
    os.setsid()

    from src.context.worker import run_worker

    asyncio.run(run_worker(poll_interval=poll_interval))


@app.command("stop")
def stop_worker():
    """Stop the Focus context worker."""
    if not PID_FILE.exists():
        console.print("[yellow]No worker PID file found. Worker may not be running.[/yellow]")
        return

    try:
        pid = int(PID_FILE.read_text().strip())
        os.kill(pid, signal.SIGTERM)
        console.print(f"[green]Sent SIGTERM to worker (PID: {pid})[/green]")
        PID_FILE.unlink(missing_ok=True)
    except ProcessLookupError:
        console.print("[yellow]Worker process not found (stale PID file). Cleaning up.[/yellow]")
        PID_FILE.unlink(missing_ok=True)
    except ValueError:
        console.print("[red]Invalid PID file. Removing.[/red]")
        PID_FILE.unlink(missing_ok=True)


@app.command("status")
def worker_status(
    verbose: bool = typer.Option(False, "--verbose", "-v"),
):
    """Show worker status and job queue stats."""
    # Check if worker is running
    running = False
    pid = None

    if PID_FILE.exists():
        try:
            pid = int(PID_FILE.read_text().strip())
            os.kill(pid, 0)  # Check if process exists
            running = True
        except (ProcessLookupError, ValueError):
            running = False

    if running:
        console.print(f"[green]Worker running[/green] (PID: {pid})")
    else:
        console.print("[yellow]Worker not running[/yellow]")

    # Show job stats
    async def _stats():
        from src.storage.db import get_session
        from src.storage.jobs import get_job_stats

        try:
            async with get_session() as session:
                stats = await get_job_stats(session)

            if stats:
                console.print("\n[bold]Job Queue:[/bold]")
                for status, count in sorted(stats.items()):
                    console.print(f"  {status}: {count}")
            else:
                console.print("\n[dim]No jobs in queue.[/dim]")
        except Exception as e:
            console.print(f"\n[dim]Cannot query jobs: {e}[/dim]")

    asyncio.run(_stats())

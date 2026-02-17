"""CLI commands for installing/managing Claude Code hooks."""

import json
import logging
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console

logger = logging.getLogger(__name__)
console = Console()

app = typer.Typer(no_args_is_help=True)

CLAUDE_SETTINGS_PATH = Path.home() / ".claude" / "settings.json"

# Marker to identify Focus hooks in settings.json
FOCUS_HOOK_MARKER = "focus "


def _get_focus_bin() -> str:
    """Find the full path to the focus binary.

    Checks in order: shutil.which, the venv bin dir alongside
    the running Python, then falls back to bare 'focus'.
    """
    found = shutil.which("focus")
    if found:
        return found

    # Check alongside the running Python (common for venv installs)
    venv_bin = Path(sys.executable).parent / "focus"
    if venv_bin.exists():
        return str(venv_bin)

    return "focus"


def _build_hook_command(subcommand: str) -> str:
    """Build a resilient hook command with bash guard.

    The wrapper ensures: (1) uses full path to focus binary,
    (2) silently exits 0 if focus is not installed, (3) never
    blocks Claude Code.

    Args:
        subcommand: The focus subcommand (e.g., 'record --hook').

    Returns:
        Shell command string for settings.json.
    """
    focus_bin = _get_focus_bin()
    return f"bash -c '{focus_bin} {subcommand} 2>/dev/null || true'"


def get_focus_hooks() -> dict:
    """Build hook configurations with the current focus binary path.

    Returns:
        Dict mapping hook event names to hook entry dicts.
    """
    return {
        "UserPromptSubmit": {
            "hooks": [
                {
                    "type": "command",
                    "command": _build_hook_command("retrieve --hook"),
                    "timeout": 5,
                }
            ]
        },
        "Stop": {
            "hooks": [
                {
                    "type": "command",
                    "command": _build_hook_command("record --hook"),
                    "timeout": 10,
                }
            ]
        },
    }


def _read_settings() -> dict:
    """Read existing Claude Code settings.json."""
    if CLAUDE_SETTINGS_PATH.exists():
        try:
            return json.loads(CLAUDE_SETTINGS_PATH.read_text())
        except (json.JSONDecodeError, OSError) as e:
            logger.warning("Failed to read settings.json: %s", e)
    return {}


def _write_settings(settings: dict) -> None:
    """Write settings.json atomically (temp file + rename)."""
    CLAUDE_SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)

    # Atomic write: write to temp, then rename
    tmp_fd, tmp_path = tempfile.mkstemp(
        dir=CLAUDE_SETTINGS_PATH.parent,
        suffix=".tmp",
    )
    try:
        with open(tmp_fd, "w") as f:
            json.dump(settings, f, indent=2)
            f.write("\n")
        Path(tmp_path).rename(CLAUDE_SETTINGS_PATH)
    except Exception:
        Path(tmp_path).unlink(missing_ok=True)
        raise


def _is_focus_command(cmd: str) -> bool:
    """Check if a command string is a Focus hook command.

    Detects both old-style ('focus retrieve --hook') and new-style
    ('bash -c '/path/to/focus retrieve --hook ...') commands.

    Args:
        cmd: The command string from settings.json.

    Returns:
        True if this is a Focus hook command.
    """
    if FOCUS_HOOK_MARKER in cmd:
        return True
    # Check for the binary name in bash-wrapped commands
    if "focus" in cmd and ("record" in cmd or "retrieve" in cmd):
        return True
    return False


def _has_focus_hook(hook_entries: list) -> bool:
    """Check if any hook entry contains a Focus command."""
    for entry in hook_entries:
        hooks = entry.get("hooks", [])
        for hook in hooks:
            if _is_focus_command(hook.get("command", "")):
                return True
    return False


def _remove_focus_hooks(hook_entries: list) -> list:
    """Remove Focus hooks from a list of hook entries."""
    result = []
    for entry in hook_entries:
        hooks = entry.get("hooks", [])
        non_focus_hooks = [
            h for h in hooks
            if not _is_focus_command(h.get("command", ""))
        ]
        if non_focus_hooks:
            result.append({**entry, "hooks": non_focus_hooks})
    return result


@app.command("install")
def install_hooks(
    force: bool = typer.Option(False, "--force", help="Overwrite existing Focus hooks"),
    verbose: bool = typer.Option(False, "--verbose", "-v"),
):
    """Install Focus hooks into Claude Code settings.json.

    Non-destructive: preserves existing hooks from other tools.
    """
    if verbose:
        logging.basicConfig(level=logging.DEBUG)

    settings = _read_settings()
    hooks = settings.get("hooks", {})

    installed = 0
    skipped = 0

    focus_hooks = get_focus_hooks()
    for event_name, focus_entry in focus_hooks.items():
        existing = hooks.get(event_name, [])

        if _has_focus_hook(existing):
            if force:
                existing = _remove_focus_hooks(existing)
                console.print(f"  [yellow]Replacing[/yellow] {event_name} hook")
            else:
                console.print(f"  [dim]Skipping[/dim] {event_name} (already installed, use --force to replace)")
                skipped += 1
                continue

        existing.append(focus_entry)
        hooks[event_name] = existing
        installed += 1
        console.print(f"  [green]Installed[/green] {event_name} hook")

    settings["hooks"] = hooks
    _write_settings(settings)

    console.print(f"\n[bold green]Hooks installed: {installed}[/bold green]", end="")
    if skipped:
        console.print(f" [dim](skipped: {skipped})[/dim]", end="")
    console.print(f"\n  Settings: {CLAUDE_SETTINGS_PATH}")


@app.command("uninstall")
def uninstall_hooks(
    verbose: bool = typer.Option(False, "--verbose", "-v"),
):
    """Remove Focus hooks from Claude Code settings.json."""
    if verbose:
        logging.basicConfig(level=logging.DEBUG)

    settings = _read_settings()
    hooks = settings.get("hooks", {})

    removed = 0

    for event_name in list(hooks.keys()):
        entries = hooks[event_name]
        if _has_focus_hook(entries):
            hooks[event_name] = _remove_focus_hooks(entries)
            if not hooks[event_name]:
                del hooks[event_name]
            removed += 1
            console.print(f"  [red]Removed[/red] {event_name} hook")

    settings["hooks"] = hooks
    _write_settings(settings)

    if removed:
        console.print(f"\n[bold]Removed {removed} Focus hooks[/bold]")
    else:
        console.print("\n[dim]No Focus hooks found to remove.[/dim]")


@app.command("status")
def hooks_status(
    verbose: bool = typer.Option(False, "--verbose", "-v"),
):
    """Show which Focus hooks are installed."""
    if verbose:
        logging.basicConfig(level=logging.DEBUG)

    if not CLAUDE_SETTINGS_PATH.exists():
        console.print("[yellow]No settings.json found at %s[/yellow]" % CLAUDE_SETTINGS_PATH)
        console.print("Run [cyan]focus hooks install[/cyan] to set up hooks.")
        return

    settings = _read_settings()
    hooks = settings.get("hooks", {})

    console.print(f"\n[bold]Focus Hook Status[/bold]  ({CLAUDE_SETTINGS_PATH})\n")

    for event_name in ["UserPromptSubmit", "Stop", "SessionStart"]:
        entries = hooks.get(event_name, [])
        if _has_focus_hook(entries):
            console.print(f"  [green]installed[/green]  {event_name}")
        else:
            console.print(f"  [dim]not installed[/dim]  {event_name}")

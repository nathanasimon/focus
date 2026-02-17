"""Project selection state — pure sync, no DB, no async.

Manages the active project selection via a local JSON state file.
Used by classifier and worker to know which project context to load.
"""

import json
import logging
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

STATE_FILE = Path.home() / ".config" / "focus" / "active_project.json"


def _read_state() -> dict:
    """Read the project state file.

    Returns:
        State dict with 'global' and 'workspaces' keys.
    """
    if not STATE_FILE.exists():
        return {"global": None, "workspaces": {}}
    try:
        data = json.loads(STATE_FILE.read_text())
        if not isinstance(data, dict):
            return {"global": None, "workspaces": {}}
        data.setdefault("global", None)
        data.setdefault("workspaces", {})
        return data
    except (json.JSONDecodeError, OSError) as e:
        logger.warning("Failed to read project state: %s", e)
        return {"global": None, "workspaces": {}}


def _write_state(state: dict) -> None:
    """Write the project state file atomically.

    Args:
        state: State dict to write.
    """
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = STATE_FILE.with_suffix(".tmp")
    try:
        tmp.write_text(json.dumps(state, indent=2) + "\n")
        tmp.rename(STATE_FILE)
    except Exception:
        tmp.unlink(missing_ok=True)
        raise


def get_active_project(workspace: Optional[str] = None) -> Optional[str]:
    """Get the active project slug.

    Priority: per-workspace override > global > None.

    Args:
        workspace: Workspace path (e.g., '/home/user/focus').

    Returns:
        Project slug or None.
    """
    state = _read_state()

    if workspace:
        ws_slug = state.get("workspaces", {}).get(workspace)
        if ws_slug:
            return ws_slug

    return state.get("global")


def set_active_project(slug: str, workspace: Optional[str] = None) -> None:
    """Set the active project.

    Args:
        slug: Project slug to set as active.
        workspace: If provided, sets per-workspace override.
            Otherwise sets global default.
    """
    state = _read_state()

    if workspace:
        state["workspaces"][workspace] = slug
    else:
        state["global"] = slug

    _write_state(state)
    logger.info("Active project set: %s (workspace=%s)", slug, workspace)


def clear_active_project(workspace: Optional[str] = None) -> None:
    """Clear the active project selection.

    Args:
        workspace: If provided, clears per-workspace override.
            Otherwise clears global default.
    """
    state = _read_state()

    if workspace:
        state.get("workspaces", {}).pop(workspace, None)
    else:
        state["global"] = None

    _write_state(state)
    logger.info("Active project cleared (workspace=%s)", workspace)


def list_active_projects() -> dict:
    """Get the full active project state.

    Returns:
        Dict with 'global' and 'workspaces' keys.
    """
    return _read_state()

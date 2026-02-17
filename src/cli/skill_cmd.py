"""CLI commands for managing Claude Code skills."""

import asyncio
import logging
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.table import Table

logger = logging.getLogger(__name__)
console = Console()

app = typer.Typer(no_args_is_help=True)


@app.command("create")
def create_skill(
    description: str = typer.Argument(help="What the skill should do"),
    scope: str = typer.Option("personal", "--scope", "-s", help="personal or project"),
    name: Optional[str] = typer.Option(None, "--name", "-n", help="Override skill name"),
    verbose: bool = typer.Option(False, "--verbose", "-v"),
):
    """Generate a new Claude Code skill from a description."""
    asyncio.run(_create(description, scope, name, verbose))


async def _create(description: str, scope: str, name: Optional[str], verbose: bool) -> None:
    """Async implementation of skill creation."""
    from src.skills.generator import GeneratedSkill, SkillContext, generate_skill_md
    from src.skills.installer import install_skill

    console.print(f"[bold]Generating skill:[/bold] {description}")

    # Build context from current directory
    context = SkillContext(workspace_path=str(Path.cwd()))

    # Try to read CLAUDE.md for conventions
    claude_md = Path.cwd() / "CLAUDE.md"
    if claude_md.exists():
        context.conventions = claude_md.read_text()[:1000]

    skill = await generate_skill_md(description, context, source="manual")
    if not skill:
        console.print("[red]Failed to generate skill. Check API key and logs.[/red]")
        raise typer.Exit(1)

    if name:
        from src.skills.generator import render_skill_md, validate_skill_name

        skill.name = validate_skill_name(name)
        skill.full_content = render_skill_md(
            name=skill.name,
            description=skill.description,
            body=skill.body,
        )

    try:
        path = install_skill(
            name=skill.name,
            content=skill.full_content,
            scope=scope,
            project_path=Path.cwd() if scope == "project" else None,
        )
        console.print(f"[green]Skill '{skill.name}' created at {path}[/green]")
    except FileExistsError as e:
        console.print(f"[yellow]{e}[/yellow]")
        raise typer.Exit(1)
    except ValueError as e:
        console.print(f"[red]Validation error: {e}[/red]")
        raise typer.Exit(1)


@app.command("list")
def list_skills(
    scope: str = typer.Option("all", "--scope", "-s", help="personal, project, or all"),
):
    """List installed Claude Code skills."""
    from src.skills.installer import list_installed_skills

    skills = list_installed_skills(
        scope=scope,
        project_path=Path.cwd() if scope in ("project", "all") else None,
    )

    if not skills:
        console.print("[dim]No skills installed.[/dim]")
        return

    table = Table(title="Installed Skills")
    table.add_column("Name", style="bold")
    table.add_column("Description")
    table.add_column("Scope", style="dim")
    table.add_column("Path", style="dim")

    for skill in skills:
        table.add_row(
            skill.name,
            skill.description[:60] + ("..." if len(skill.description) > 60 else ""),
            skill.scope,
            str(skill.path.parent),
        )

    console.print(table)


@app.command("show")
def show_skill(
    name: str = typer.Argument(help="Skill name to show"),
    scope: str = typer.Option("all", "--scope", "-s", help="personal, project, or all"),
):
    """Show the contents of an installed skill."""
    from src.skills.installer import list_installed_skills

    skills = list_installed_skills(
        scope=scope,
        project_path=Path.cwd() if scope in ("project", "all") else None,
    )

    for skill in skills:
        if skill.name == name:
            content = skill.path.read_text()
            console.print(f"[bold]{skill.path}[/bold]\n")
            console.print(content)
            return

    console.print(f"[red]Skill '{name}' not found.[/red]")
    raise typer.Exit(1)


@app.command("uninstall")
def uninstall(
    name: str = typer.Argument(help="Skill name to remove"),
    scope: str = typer.Option("personal", "--scope", "-s", help="personal or project"),
):
    """Remove an installed skill."""
    from src.skills.installer import uninstall_skill

    removed = uninstall_skill(
        name=name,
        scope=scope,
        project_path=Path.cwd() if scope == "project" else None,
    )

    if removed:
        console.print(f"[green]Uninstalled skill '{name}'[/green]")
    else:
        console.print(f"[red]Skill '{name}' not found in {scope} scope.[/red]")
        raise typer.Exit(1)


@app.command("search")
def search(
    query: str = typer.Argument(help="Search query"),
    source: Optional[str] = typer.Option(None, "--source", help="Specific GitHub repo to search"),
    verbose: bool = typer.Option(False, "--verbose", "-v"),
):
    """Search public skill registries."""
    asyncio.run(_search(query, source, verbose))


async def _search(query: str, source: Optional[str], verbose: bool) -> None:
    """Async implementation of skill search."""
    from src.skills.registry import search_skills

    console.print(f"[bold]Searching for:[/bold] {query}")

    sources = [source] if source else None
    results = await search_skills(query, sources)

    if not results:
        console.print("[dim]No skills found matching your query.[/dim]")
        return

    table = Table(title=f"Skills matching '{query}'")
    table.add_column("Name", style="bold")
    table.add_column("Description")
    table.add_column("Source", style="dim")

    for skill in results:
        table.add_row(
            skill.name,
            skill.description[:60] + ("..." if len(skill.description) > 60 else ""),
            skill.source_repo,
        )

    console.print(table)
    console.print(
        f"\n[dim]Install with: focus skill install <repo>/<path>[/dim]"
    )


@app.command("install")
def install(
    source: str = typer.Argument(help="GitHub repo/path (e.g. anthropics/skills/web-search)"),
    scope: str = typer.Option("personal", "--scope", "-s", help="personal or project"),
    force: bool = typer.Option(False, "--force", "-f", help="Overwrite existing skill"),
):
    """Install a skill from a GitHub repository."""
    asyncio.run(_install(source, scope, force))


async def _install(source: str, scope: str, force: bool) -> None:
    """Async implementation of skill install."""
    from src.skills.installer import install_skill
    from src.skills.registry import fetch_skill_from_github

    # Parse source into repo + path
    parts = source.split("/", 2)
    if len(parts) < 3:
        console.print("[red]Expected format: owner/repo/skill-path[/red]")
        raise typer.Exit(1)

    repo = f"{parts[0]}/{parts[1]}"
    skill_path = parts[2]

    console.print(f"[bold]Fetching:[/bold] {repo}/{skill_path}")

    skill = await fetch_skill_from_github(repo, skill_path)
    if not skill:
        console.print(f"[red]Could not find skill at {source}[/red]")
        raise typer.Exit(1)

    try:
        path = install_skill(
            name=skill.name,
            content=skill.skill_md_content,
            scope=scope,
            project_path=Path.cwd() if scope == "project" else None,
            force=force,
            supporting_files=skill.supporting_files or None,
        )
        console.print(f"[green]Installed '{skill.name}' at {path}[/green]")
    except FileExistsError as e:
        console.print(f"[yellow]{e}[/yellow]")
        raise typer.Exit(1)
    except ValueError as e:
        console.print(f"[red]Validation error: {e}[/red]")
        raise typer.Exit(1)


@app.command("auto-scan")
def auto_scan(
    dry_run: bool = typer.Option(False, "--dry-run", help="Show candidates without generating"),
    min_quality: float = typer.Option(0.6, "--min-quality", help="Minimum quality score"),
):
    """Scan recent sessions and auto-generate skills from good ones."""
    asyncio.run(_auto_scan(dry_run, min_quality))


async def _auto_scan(dry_run: bool, min_quality: float) -> None:
    """Async implementation of auto-scan."""
    from sqlalchemy import select
    from sqlalchemy.orm import selectinload

    from src.skills.analyzer import analyze_session_for_skill
    from src.skills.generator import generate_skill_md
    from src.skills.installer import install_skill
    from src.storage.db import get_session
    from src.storage.models import AgentSession

    async with get_session() as session:
        result = await session.execute(
            select(AgentSession)
            .where(AgentSession.is_processed.is_(True))
            .options(selectinload(AgentSession.turns))
            .order_by(AgentSession.last_activity_at.desc())
            .limit(20)
        )
        sessions = result.scalars().all()

    if not sessions:
        console.print("[dim]No processed sessions found.[/dim]")
        return

    candidates = []
    async with get_session() as db_session:
        for agent_session in sessions:
            candidate = await analyze_session_for_skill(db_session, agent_session)
            if candidate and candidate.quality_score >= min_quality:
                candidates.append(candidate)

    if not candidates:
        console.print("[dim]No sessions qualified for skill generation.[/dim]")
        return

    console.print(f"[bold]Found {len(candidates)} skill candidate(s):[/bold]")

    for c in candidates:
        console.print(
            f"  [cyan]{c.session_id[:12]}[/cyan] "
            f"(quality: {c.quality_score:.2f}) "
            f"{c.description[:60]}"
        )

    if dry_run:
        console.print("\n[dim]Dry run — no skills generated.[/dim]")
        return

    for c in candidates:
        skill = await generate_skill_md(c.description, c.context, source="auto")
        if skill:
            try:
                path = install_skill(name=skill.name, content=skill.full_content)
                console.print(f"[green]Generated skill '{skill.name}' at {path}[/green]")
            except (FileExistsError, ValueError) as e:
                console.print(f"[yellow]Skipped: {e}[/yellow]")

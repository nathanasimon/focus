"""CLI command for context retrieval (UserPromptSubmit hook)."""

import asyncio
import json
import logging
import sys
from typing import Optional

import typer
from rich.console import Console

logger = logging.getLogger(__name__)
console = Console()

app = typer.Typer(invoke_without_command=True)


@app.callback(invoke_without_command=True)
def retrieve(
    hook: bool = typer.Option(False, "--hook", help="Read stdin JSON (Claude Code hook mode)"),
    query: Optional[str] = typer.Option(None, "--query", "-q", help="Manual query for testing"),
    cwd: Optional[str] = typer.Option(None, "--cwd", help="Simulate working directory"),
    max_tokens: int = typer.Option(1500, "--tokens", help="Token budget"),
    verbose: bool = typer.Option(False, "--verbose", "-v"),
):
    """Retrieve context for a prompt."""
    if hook:
        _hook_retrieve()
    elif query:
        _manual_retrieve(query, cwd, max_tokens, verbose)
    else:
        console.print("Usage: focus retrieve --hook (for Claude Code) or --query (for testing)")


def _hook_retrieve():
    """Hook path: read stdin, classify, retrieve, output JSON.

    This entire path must complete in <2 seconds.
    """
    try:
        input_data = json.loads(sys.stdin.read())
    except (json.JSONDecodeError, ValueError):
        sys.exit(0)

    prompt = input_data.get("prompt", "")
    cwd = input_data.get("cwd", "")

    if not prompt:
        sys.exit(0)

    async def _retrieve():
        from src.context.classifier import PromptClassifier
        from src.context.formatter import format_context_blocks
        from src.context.retriever import ContextRetriever
        from src.config import get_settings
        from src.storage.db import get_session

        settings = get_settings()
        if not settings.context.enabled or not settings.context.retrieval_enabled:
            return ""

        async with get_session() as session:
            classifier = PromptClassifier()
            await classifier.load_entities(session)

            classification = classifier.classify(prompt, cwd)

            if classification.confidence < 0.1:
                return ""

            retriever = ContextRetriever()
            blocks = await retriever.retrieve(
                session, classification, max_tokens=settings.context.max_context_tokens
            )

            return format_context_blocks(blocks, max_tokens=settings.context.max_context_tokens)

    try:
        context_text = asyncio.run(_retrieve())
    except Exception:
        sys.exit(0)

    if context_text:
        output = {
            "hookSpecificOutput": {
                "hookEventName": "UserPromptSubmit",
                "additionalContext": context_text,
            }
        }
        print(json.dumps(output))

    sys.exit(0)


def _manual_retrieve(query: str, cwd: Optional[str], max_tokens: int, verbose: bool):
    """Manual mode for testing retrieval."""
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
            console.print(f"  Projects:  {classification.project_slugs or '(none)'}")
            console.print(f"  People:    {classification.person_names or '(none)'}")
            console.print(f"  Type:      {classification.query_type}")
            console.print(f"  Workspace: {classification.workspace_project or '(none)'}")
            console.print(f"  Confidence: {classification.confidence:.1%}")

            if classification.confidence < 0.1:
                console.print("\n[yellow]Confidence too low, no context would be injected.[/yellow]")
                return

            retriever = ContextRetriever()
            blocks = await retriever.retrieve(session, classification, max_tokens=max_tokens)

            console.print(f"\n[bold]Retrieved {len(blocks)} context blocks:[/bold]")
            for block in blocks:
                console.print(f"  [{block.source_type}] {block.title} (score: {block.relevance_score:.1f})")

            formatted = format_context_blocks(blocks, max_tokens=max_tokens)
            if formatted:
                console.print(f"\n[bold]Formatted output ({len(formatted)} chars, ~{len(formatted)//4} tokens):[/bold]")
                console.print(formatted)
            else:
                console.print("\n[yellow]No context to inject.[/yellow]")

    asyncio.run(_run())

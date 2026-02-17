"""CLI commands for managing email accounts."""

import asyncio

import typer
from rich.console import Console
from rich.table import Table

app = typer.Typer(no_args_is_help=True)
console = Console()


@app.command("add")
def add_account(
    name: str = typer.Option(..., prompt="Account name (e.g., personal, work, school)"),
    email: str = typer.Option(..., prompt="Email address"),
    provider: str = typer.Option("gmail", help="Email provider"),
    priority: float = typer.Option(1.0, "--priority", "-p", help="Priority weight"),
    newsletters: bool = typer.Option(False, "--newsletters", help="Process newsletters"),
):
    """Add a new email account with OAuth."""

    async def _add():
        from src.ingestion.accounts import add_account as _add_account
        from src.ingestion.accounts import store_oauth_token
        from src.ingestion.gmail import run_oauth_flow
        from src.storage.db import get_session

        async with get_session() as session:
            # Create account record
            account = await _add_account(
                session,
                name=name,
                email=email,
                provider=provider,
                priority_weight=priority,
                process_newsletters=newsletters,
            )

            console.print(f"\n[bold]Account created: {name} ({email})[/bold]")

            # Run OAuth flow
            console.print("\nStarting OAuth flow — a browser window will open...")
            try:
                token_data = run_oauth_flow()
                await store_oauth_token(session, account.id, token_data)
                console.print("[green]OAuth authorized successfully![/green]")
            except Exception as e:
                console.print(f"[yellow]OAuth skipped: {e}[/yellow]")
                console.print("You can set up OAuth later by running: focus account auth " + name)

            console.print(f"\nAccount [cyan]{name}[/cyan] is ready. Run [cyan]focus sync[/cyan] to fetch emails.")

    asyncio.run(_add())


@app.command("list")
def list_accounts():
    """Show all configured email accounts."""

    async def _list():
        from src.ingestion.accounts import list_accounts as _list_accounts
        from src.storage.db import get_session

        async with get_session() as session:
            accounts = await _list_accounts(session)

            if not accounts:
                console.print("[yellow]No accounts configured. Run: focus account add[/yellow]")
                return

            table = Table(title="Email Accounts")
            table.add_column("Name", style="cyan")
            table.add_column("Email")
            table.add_column("Provider")
            table.add_column("Priority", justify="right")
            table.add_column("Sync", justify="center")
            table.add_column("Last Sync")
            table.add_column("OAuth")

            for account in accounts:
                sync_icon = "[green]ON[/green]" if account.sync_enabled else "[red]OFF[/red]"
                last_sync = account.last_sync.strftime("%Y-%m-%d %H:%M") if account.last_sync else "never"
                oauth_status = "[green]OK[/green]" if account.oauth_token else "[red]missing[/red]"
                table.add_row(
                    account.name,
                    account.email,
                    account.provider,
                    f"{account.priority_weight:.1f}",
                    sync_icon,
                    last_sync,
                    oauth_status,
                )

            console.print(table)

    asyncio.run(_list())


@app.command("priority")
def set_priority(
    name: str = typer.Argument(help="Account name"),
    weight: float = typer.Argument(help="Priority weight (e.g., 1.0, 1.5, 2.0)"),
):
    """Set priority weight for an account."""

    async def _set():
        from src.ingestion.accounts import get_account_by_name, update_account_priority
        from src.storage.db import get_session

        async with get_session() as session:
            account = await get_account_by_name(session, name)
            if not account:
                console.print(f"[red]Account not found: {name}[/red]")
                raise typer.Exit(1)

            await update_account_priority(session, account.id, weight)
            console.print(f"Account [cyan]{name}[/cyan] priority set to [bold]{weight}[/bold]")

    asyncio.run(_set())


@app.command("disable")
def disable(name: str = typer.Argument(help="Account name")):
    """Disable syncing for an account."""

    async def _disable():
        from src.ingestion.accounts import disable_account, get_account_by_name
        from src.storage.db import get_session

        async with get_session() as session:
            account = await get_account_by_name(session, name)
            if not account:
                console.print(f"[red]Account not found: {name}[/red]")
                raise typer.Exit(1)

            await disable_account(session, account.id)
            console.print(f"Account [cyan]{name}[/cyan] sync disabled")

    asyncio.run(_disable())


@app.command("enable")
def enable(name: str = typer.Argument(help="Account name")):
    """Enable syncing for an account."""

    async def _enable():
        from src.ingestion.accounts import enable_account, get_account_by_name
        from src.storage.db import get_session

        async with get_session() as session:
            account = await get_account_by_name(session, name)
            if not account:
                console.print(f"[red]Account not found: {name}[/red]")
                raise typer.Exit(1)

            await enable_account(session, account.id)
            console.print(f"Account [cyan]{name}[/cyan] sync enabled")

    asyncio.run(_enable())


@app.command("auth")
def auth(name: str = typer.Argument(help="Account name to re-authorize")):
    """Re-run OAuth flow for an account."""

    async def _auth():
        from src.ingestion.accounts import get_account_by_name, store_oauth_token
        from src.ingestion.gmail import run_oauth_flow
        from src.storage.db import get_session

        async with get_session() as session:
            account = await get_account_by_name(session, name)
            if not account:
                console.print(f"[red]Account not found: {name}[/red]")
                raise typer.Exit(1)

            console.print(f"Starting OAuth flow for [cyan]{name}[/cyan]...")
            token_data = run_oauth_flow()
            await store_oauth_token(session, account.id, token_data)
            console.print("[green]OAuth authorized successfully![/green]")

    asyncio.run(_auth())

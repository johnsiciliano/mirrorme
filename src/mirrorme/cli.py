from __future__ import annotations

import typer
from rich import print
from typing import Optional, List

from .mirror import MirrorConfig, run_mirror

app = typer.Typer(help="Playwright-powered offline website mirroring with relative links.")

@app.command()
def main(
    url: str = typer.Argument(..., help="Start URL, e.g. https://example.com/"),
    out: str = typer.Option("site_mirror", "--out", "-o", help="Output directory."),
    depth: int = typer.Option(3, "--depth", "-d", help="Max link depth to follow."),
    allow_host: List[str] = typer.Option(
        None, "--allow-host", "-H",
        help="Additional host(s) allowed to mirror (repeat flag). Defaults to start host only."
    ),
    include_assets_offsite: bool = typer.Option(
        True, "--assets-offsite/--no-assets-offsite",
        help="Save assets (img/css/js/fonts) from allowed hosts even if page link traversal is restricted."
    ),
    user_agent: str = typer.Option(
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "--user-agent", help="Custom User-Agent."
    ),
    storage_state: Optional[str] = typer.Option(
        None, "--storage-state", "-S",
        help="Playwright storage state JSON for authenticated mirroring."
    ),
    headless: bool = typer.Option(True, "--headless/--headed", help="Run browser headless or visible."),
    concurrency: int = typer.Option(4, "--concurrency", "-c", help="Max concurrent page fetches (politeness first)."),
    timeout_ms: int = typer.Option(30000, "--timeout-ms", help="Default navigation timeout per page."),
):
    """
    Mirror a site to a local folder and rewrite links to relative paths.
    """
    cfg = MirrorConfig(
        start_url=url,
        out_dir=out,
        max_depth=depth,
        extra_allowed_hosts=set(allow_host or []),
        include_assets_offsite=include_assets_offsite,
        user_agent=user_agent,
        storage_state_path=storage_state,
        headless=headless,
        concurrency=max(1, concurrency),
        default_timeout_ms=timeout_ms,
    )
    print(f"[bold cyan]mirrorme[/] -> [green]{url}[/]  [dim]→[/]  [magenta]{out}[/]")
    run_mirror(cfg)
    print("[bold green]Done.[/]")


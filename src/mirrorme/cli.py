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
        help="Additional host(s) allowed for traversal/assets (repeat flag). Defaults to start host only."
    ),
    include_assets_offsite: bool = typer.Option(
        True, "--assets-offsite/--no-assets-offsite",
        help="Save assets (img/css/js/fonts) from allowed hosts."
    ),
    all_host_assets: bool = typer.Option(
        False, "--all-host-assets/--no-all-host-assets",
        help="Save assets from ANY host (but still only traverse HTML on the start host)."
    ),
    inline_css_imports: bool = typer.Option(
        True, "--inline-css-imports/--no-inline-css-imports",
        help="Resolve and download CSS @import URLs found inside stylesheets."
    ),
    strip_csp: bool = typer.Option(
        True, "--strip-csp/--keep-csp",
        help="Remove meta Content-Security-Policy tags so local assets load from file://."
    ),
    user_agent: str = typer.Option(
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "--user-agent", help="Custom User-Agent."
    ),
    storage_state: Optional[str] = typer.Option(
        None, "--storage-state", "-S",
        help="Playwright storage state JSON for authenticated mirroring."
    ),
    flat_assets: bool = typer.Option(
        True, "--flat-assets/--per-host-assets",
        help="Save all non-HTML under a single assets/ folder (no per-host dirs)."
    ),
    headless: bool = typer.Option(True, "--headless/--headed", help="Run browser headless or visible."),
    concurrency: int = typer.Option(4, "--concurrency", "-c", help="Max concurrent page fetches."),
    timeout_ms: int = typer.Option(30000, "--timeout-ms", help="Default navigation timeout per page."),
    scroll: bool = typer.Option(
        True, "--scroll/--no-scroll",
        help="Auto-scroll pages to trigger lazy-loaded assets."
    ),
    wait_after_load_ms: int = typer.Option(
        800, "--wait-after-load-ms",
        help="Extra wait after networkidle to let JS/lazy loaders fetch assets."
    ),
        # NEW ↓↓↓
    assets_mode: str = typer.Option(
        "flat", "--assets-mode",
        help="Where to place non-HTML: flat | per-host | pages",
        case_sensitive=False,
    ),
    assets_dir: str = typer.Option(
        "assets", "--assets-dir",
        help="Directory name for assets (used by flat/per-host modes).",
    ),
):
    cfg = MirrorConfig(
        start_url=url,
        out_dir=out,
        max_depth=depth,
        extra_allowed_hosts=set(allow_host or []),
        include_assets_offsite=include_assets_offsite,
        all_host_assets=all_host_assets,
        inline_css_imports=inline_css_imports,
        strip_csp=strip_csp,
        user_agent=user_agent,
        storage_state_path=storage_state,
        headless=headless,
        concurrency=max(1, concurrency),
        default_timeout_ms=timeout_ms,
        scroll=scroll,
        wait_after_load_ms=wait_after_load_ms,
        flat_assets=flat_assets,
        assets_mode=assets_mode.lower(),
        assets_dir=assets_dir,
    )
    print(f"[bold cyan]mirrorme[/] -> [green]{url}[/]  [dim]→[/]  [magenta]{out}[/]")
    run_mirror(cfg)
    print("[bold green]Done.[/]")

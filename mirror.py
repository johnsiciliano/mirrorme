from __future__ import annotations

import asyncio, os, re, pathlib, urllib.parse
from dataclasses import dataclass, field
from typing import Dict, Set, Tuple, List

from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright

@dataclass
class MirrorConfig:
    start_url: str
    out_dir: str = "site_mirror"
    max_depth: int = 3
    extra_allowed_hosts: Set[str] = field(default_factory=set)
    include_assets_offsite: bool = True
    user_agent: str = (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    )
    storage_state_path: str | None = None
    headless: bool = True
    concurrency: int = 4
    default_timeout_ms: int = 30000

def url_norm(u: str) -> str:
    return urllib.parse.urldefrag(u)[0]

def to_rel_path(out_dir: pathlib.Path, url: str) -> pathlib.Path:
    p = urllib.parse.urlparse(url)
    host = p.hostname or "unknown"
    path = p.path or "/"
    if path.endswith("/"):
        path += "index.html"
    if not os.path.splitext(path)[1]:
        # If no extension and looks like a page, assume HTML
        path += ".html"
    safe = re.sub(r"[^A-Za-z0-9._/\-]", "_", path)
    return out_dir / host / safe.lstrip("/")

def ensure_parent(fp: pathlib.Path):
    fp.parent.mkdir(parents=True, exist_ok=True)

def make_relative(from_path: pathlib.Path, to_path: pathlib.Path) -> str:
    return os.path.relpath(to_path, start=from_path.parent)

def rewrite_urls_in_text(text: str, mapping: Dict[str, pathlib.Path], base_file: pathlib.Path) -> str:
    def repl_srcset(match):
        srcset = match.group(1)
        parts = []
        for token in srcset.split(","):
            token = token.strip()
            if not token:
                continue
            bits = token.split()
            url = bits[0].strip('\'"')
            rest = " ".join(bits[1:])
            if url in mapping:
                url_rel = make_relative(base_file, mapping[url])
                parts.append(f"{url_rel} {rest}".strip())
            else:
                parts.append(token)
        return 'srcset="' + ", ".join(parts) + '"'

    text = re.sub(r'srcset="([^"]+)"', repl_srcset, text)

    def sub_url(m):
        quote = m.group(1)
        url = m.group(2).strip('\'"')
        if url in mapping:
            rel = make_relative(base_file, mapping[url])
            return f'{m.group(0).split("=")[0]}={quote}{rel}{quote}'
        return m.group(0)

    text = re.sub(r'(?:src|href)\s*=\s*("|\')([^"\']+)\1', sub_url, text)

    def css_url(m):
        url = m.group(1).strip('\'"')
        if url in mapping:
            rel = make_relative(base_file, mapping[url])
            return f'url("{rel}")'
        return m.group(0)

    text = re.sub(r'url\(([^)]+)\)', css_url, text)
    return text

def run_mirror(cfg: MirrorConfig):
    out_dir = pathlib.Path(cfg.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    start = url_norm(cfg.start_url)
    start_host = urllib.parse.urlparse(start).hostname
    allowed_hosts: Set[str] = {start_host} if start_host else set()
    allowed_hosts |= set(cfg.extra_allowed_hosts)

    visited_pages: Set[str] = set()
    to_visit: List[Tuple[str, int]] = [(start, 0)]
    saved_assets: Dict[str, pathlib.Path] = {}
    page_html_paths: Dict[str, pathlib.Path] = {}

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=cfg.headless, args=["--disable-web-security"])
        context_kwargs = {"user_agent": cfg.user_agent}
        if cfg.storage_state_path:
            context_kwargs["storage_state"] = cfg.storage_state_path
        context = browser.new_context(**context_kwargs)
        context.set_default_timeout(cfg.default_timeout_ms)

        # capture all non-HTML assets
        def handle_response(res):
            try:
                url = url_norm(res.url)
                host = urllib.parse.urlparse(url).hostname
                if not host:
                    return
                if (host in allowed_hosts) and res.status == 200:
                    ct = res.headers.get("content-type", "")
                    # Let HTML be handled separately after DOM rendering
                    if "text/html" in ct:
                        return
                    path = to_rel_path(out_dir, url)
                    if url not in saved_assets:
                        body = res.body()
                        ensure_parent(path)
                        with open(path, "wb") as f:
                            f.write(body)
                        saved_assets[url] = path
            except Exception:
                pass

        context.on("response", handle_response)

        sem = asyncio.Semaphore(cfg.concurrency)

        async def fetch_page(url: str, depth: int):
            url_n = url_norm(url)
            if url_n in visited_pages:
                return
            if depth > cfg.max_depth:
                return

            visited_pages.add(url_n)
            page = await context.new_page()
            await page.set_extra_http_headers({"Accept-Language": "en-US,en;q=0.9"})
            try:
                resp = await page.goto(url_n, wait_until="networkidle")
                if not resp or resp.status != 200:
                    await page.close()
                    return

                html = await page.content()
                html_path = to_rel_path(out_dir, url_n)
                ensure_parent(html_path)
                with open(html_path, "w", encoding="utf-8") as f:
                    f.write(html)
                page_html_paths[url_n] = html_path

                soup = BeautifulSoup(html, "html.parser")

                def extract_links(attrs):
                    for tag, attr in attrs:
                        for el in soup.find_all(tag):
                            link = el.get(attr)
                            if not link:
                                continue
                            absu = urllib.parse.urljoin(url_n, link)
                            yield url_norm(absu)

                anchors = list(extract_links([("a", "href")]))
                scripts = list(extract_links([("script", "src")]))
                links = list(extract_links([("link", "href")]))
                imgs = list(extract_links([("img", "src")]))

                srcset_urls = []
                for el in soup.find_all(["img", "source"]):
                    ss = el.get("srcset")
                    if ss:
                        for token in ss.split(","):
                            token = token.strip()
                            if token:
                                src = token.split()[0]
                                absu = urllib.parse.urljoin(url_n, src)
                                srcset_urls.append(url_norm(absu))

                # Enqueue same-host HTML pages
                for a in anchors:
                    host = urllib.parse.urlparse(a).hostname
                    if host and host == start_host:
                        to_visit.append((a, depth + 1))

                # Trigger asset fetches explicitly (Playwright will honor cookies/referers)
                assets = set(scripts + links + imgs + srcset_urls)
                for asset_url in assets:
                    host = urllib.parse.urlparse(asset_url).hostname
                    if not host:
                        continue
                    if host in allowed_hosts:
                        # If offsite assets are allowed (default True), we still save them.
                        await context.request.get(asset_url)

            finally:
                await page.close()

        # Run the queue
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

        async def runner():
            while to_visit:
                batch = []
                while to_visit and len(batch) < cfg.concurrency:
                    u, d = to_visit.pop(0)
                    if u in visited_pages:
                        continue
                    batch.append((u, d))

                if not batch:
                    break

                async def _task(u, d):
                    async with sem:
                        await fetch_page(u, d)

                await asyncio.gather(*[_task(u, d) for (u, d) in batch])

        loop.run_until_complete(runner())

        # Build mapping and rewrite HTML
        mapping = {u: p for (u, p) in saved_assets.items()}
        for u, p in page_html_paths.items():
            mapping[u] = p

        for u, p in page_html_paths.items():
            with open(p, "r", encoding="utf-8") as f:
                txt = f.read()
            new_txt = rewrite_urls_in_text(txt, mapping, p)
            if new_txt != txt:
                with open(p, "w", encoding="utf-8") as f:
                    f.write(new_txt)

        # Simple index
        index_path = pathlib.Path(cfg.out_dir) / "index.html"
        ensure_parent(index_path)
        with open(index_path, "w", encoding="utf-8") as f:
            f.write("<h1>Local Mirror</h1><ul>\n")
            for u, p in sorted(page_html_paths.items()):
                rel = os.path.relpath(p, start=out_dir)
                f.write(f'<li><a href="{rel}">{u}</a></li>\n')
            f.write("</ul>\n")

        browser.close()


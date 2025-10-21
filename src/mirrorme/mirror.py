from __future__ import annotations

import asyncio, os, re, pathlib, urllib.parse
from dataclasses import dataclass, field
from typing import Dict, Set, Tuple, List
import hashlib
from bs4 import BeautifulSoup
from playwright.async_api import async_playwright, BrowserContext


_ASSET_EXTS = {
    ".png",".jpg",".jpeg",".webp",".avif",".gif",".svg",".ico",".bmp",".tiff",
    ".css",".js",".mjs",".map",
    ".woff",".woff2",".ttf",".otf",".eot",
    ".mp4",".webm",".ogg",".mp3",".wav",".mov",".m4a",".m4v",
    ".pdf",".txt",".xml",".json",".wasm"
}

@dataclass
class MirrorConfig:
    start_url: str
    out_dir: str = "site_mirror"
    max_depth: int = 3
    extra_allowed_hosts: Set[str] = field(default_factory=set)
    include_assets_offsite: bool = True
    all_host_assets: bool = False          # NEW: capture assets from any host
    inline_css_imports: bool = True        # NEW: follow @import inside CSS
    strip_csp: bool = True                 # NEW: strip <meta http-equiv="Content-Security-Policy">
    user_agent: str = (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    )
    storage_state_path: str | None = None
    headless: bool = True
    concurrency: int = 4
    default_timeout_ms: int = 30000
    scroll: bool = True                    # NEW: simulate user scroll for lazy loading
    wait_after_load_ms: int = 800          # NEW: extra idle wait
    flat_assets: bool = True  
    assets_mode: str = "flat"   # flat | per-host | pages
    assets_dir: str = "assets"  # used for flat/per-host

def url_norm(u: str) -> str:
    return urllib.parse.urldefrag(u)[0]

def _is_asset(path: str) -> bool:
    return os.path.splitext(path)[1].lower() in _ASSET_EXTS

def _safe_path(s: str) -> str:
    return re.sub(r"[^A-Za-z0-9._/\-]", "_", s)

def to_rel_path(out_dir: pathlib.Path, url: str, cfg, start_host: str, is_html_hint: bool | None = None) -> pathlib.Path:
    p = urllib.parse.urlparse(url)
    host = p.hostname or "unknown"
    path = p.path or "/"

    # normalize filename
    if path.endswith("/"):
        path += "index.html"
    name, ext = os.path.splitext(path)
    if not ext:
        path += ".html"
        ext = ".html"

    safe = re.sub(r"[^A-Za-z0-9._/\-]", "_", path.lstrip("/"))
    is_html = (ext.lower() == ".html") if is_html_hint is None else is_html_hint

    if is_html:
        # HTML always under pages/<host>/...
        return out_dir / "pages" / (p.hostname or start_host or "unknown") / safe

    mode = (cfg.assets_mode or "flat").lower()
    if mode == "pages":
        # ⬅️ place ALL assets under the start host’s pages tree
        # pages/<START_HOST>/<assets_dir>/<asset-host>/safe
        return out_dir / "pages" / (start_host or "unknown") / cfg.assets_dir / (host or "unknown") / safe

    elif mode == "per-host":
        return out_dir / cfg.assets_dir / host / safe

    else:  # flat
        target = out_dir / cfg.assets_dir / safe
        if target.exists():
            h = hashlib.sha1(url.encode("utf-8")).hexdigest()[:8]
            base, ext2 = os.path.splitext(target.name)
            target = target.with_name(f"{base}__{h}{ext2}")
        return target

def ensure_parent(fp: pathlib.Path):
    fp.parent.mkdir(parents=True, exist_ok=True)

def make_relative(from_path: pathlib.Path, to_path: pathlib.Path) -> str:
    return os.path.relpath(to_path, start=from_path.parent)

CSS_IMPORT_RE = re.compile(r'@import\s+(?:url\()?["\']?([^"\')]+)["\']?\)?\s*;', re.IGNORECASE)

def rewrite_urls_in_text(text: str, mapping: Dict[str, pathlib.Path], base_file: pathlib.Path, strip_csp: bool) -> str:
    # Strip CSP meta to avoid file:// blocking
    if strip_csp:
        text = re.sub(
            r'<meta[^>]+http-equiv=["\']Content-Security-Policy["\'][^>]*>',
            '',
            text,
            flags=re.IGNORECASE
        )

    # srcset
    def repl_srcset(m):
        parts, srcset = [], m.group(1)
        for tok in srcset.split(","):
            tok = tok.strip()
            if not tok:
                continue
            bits = tok.split()
            u = bits[0].strip('\'"')
            rest = " ".join(bits[1:])
            if u in mapping:
                rel = make_relative(base_file, mapping[u])
                parts.append(f"{rel} {rest}".strip())
            else:
                parts.append(tok)
        return f'srcset="{", ".join(parts)}"'

    text = re.sub(r'srcset="([^"]+)"', repl_srcset, text)

    # src= / href=
    def sub_url(m):
        quote, u = m.group(1), m.group(2).strip('\'"')
        if u in mapping:
            rel = make_relative(base_file, mapping[u])
            return f'{m.group(0).split("=")[0]}={quote}{rel}{quote}'
        return m.group(0)

    text = re.sub(r'(?:src|href)\s*=\s*("|\')([^"\']+)\1', sub_url, text)

    # CSS url(...)
    def css_url(m):
        u = m.group(1).strip('\'"')
        if u in mapping:
            rel = make_relative(base_file, mapping[u])
            return f'url("{rel}")'
        return m.group(0)

    text = re.sub(r'url\(([^)]+)\)', css_url, text)
    return text

async def run_mirror_async(cfg: MirrorConfig):
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

    sem = asyncio.Semaphore(max(1, cfg.concurrency))

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=cfg.headless, args=["--disable-web-security"])
        context_kwargs = {"user_agent": cfg.user_agent}
        if cfg.storage_state_path:
            context_kwargs["storage_state"] = cfg.storage_state_path
        context: BrowserContext = await browser.new_context(**context_kwargs)
        context.set_default_timeout(cfg.default_timeout_ms)

        # Capture ALL non-HTML assets. If all_host_assets=True, we don't restrict host here.
        async def handle_response(res):
            try:
                url = url_norm(res.url)
                host = urllib.parse.urlparse(url).hostname or ""
                status = res.status
                if status != 200:
                    return
                headers = await res.all_headers()
                ct = headers.get("content-type", "")
                if "text/html" in (ct or ""):
                    return
                if (host in allowed_hosts) or cfg.all_host_assets:
                    path = to_rel_path(out_dir, url, cfg, start_host, is_html_hint=False)
                    if url not in saved_assets:
                        body = await res.body()
                        ensure_parent(path)
                        with open(path, "wb") as f:
                            f.write(body)
                        saved_assets[url] = path
            except Exception:
                pass

        context.on("response", handle_response)

        async def fetch_page(url: str, depth: int):
            url_n = url_norm(url)
            if url_n in visited_pages or depth > cfg.max_depth:
                return
            visited_pages.add(url_n)

            page = await context.new_page()
            await page.set_extra_http_headers({"Accept-Language": "en-US,en;q=0.9"})
            try:
                resp = await page.goto(url_n, wait_until="networkidle")
                if not resp or resp.status != 200:
                    await page.close()
                    return

                # lazy-load triggers
                if cfg.scroll:
                    # scroll to bottom in steps
                    await page.evaluate("""
                        (async () => {
                          const delay = ms => new Promise(r => setTimeout(r, ms));
                          let last = 0;
                          for (let i=0;i<10;i++){
                            window.scrollTo(0, document.body.scrollHeight);
                            await delay(150);
                            const h = document.body.scrollHeight;
                            if (h === last) break;
                            last = h;
                          }
                          window.scrollTo(0, 0);
                        })();
                    """)
                if cfg.wait_after_load_ms > 0:
                    await page.wait_for_timeout(cfg.wait_after_load_ms)

                html = await page.content()
                html_path = to_rel_path(out_dir, url_n, cfg, start_host, is_html_hint=True)
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

                anchors = list(extract_links([("a","href")]))
                scripts = list(extract_links([("script","src")]))
                links   = list(extract_links([("link","href")]))
                imgs    = list(extract_links([("img","src")]))
                media   = list(extract_links([("source","src"), ("video","src"), ("audio","src")]))
                # srcset
                srcset_urls = []
                for el in soup.find_all(["img","source"]):
                    ss = el.get("srcset")
                    if ss:
                        for token in ss.split(","):
                            token = token.strip()
                            if token:
                                src = token.split()[0]
                                absu = urllib.parse.urljoin(url_n, src)
                                srcset_urls.append(url_norm(absu))

                # queue same-host pages only
                for a in anchors:
                    host = urllib.parse.urlparse(a).hostname
                    if host and host == start_host:
                        to_visit.append((a, depth + 1))

                # trigger asset fetches (any host if all_host_assets=True)
                assets = set(scripts + links + imgs + media + srcset_urls)
                for asset_url in assets:
                    host = urllib.parse.urlparse(asset_url).hostname or ""
                    if cfg.all_host_assets or host in allowed_hosts:
                        await context.request.get(asset_url)

            finally:
                await page.close()

        # Process queue in batches
        while to_visit:
            batch: List[Tuple[str,int]] = []
            while to_visit and len(batch) < cfg.concurrency:
                u,d = to_visit.pop(0)
                if u not in visited_pages:
                    batch.append((u,d))
            if not batch:
                break
            async def _task(u,d):
                async with sem:
                    await fetch_page(u,d)
            await asyncio.gather(*(_task(u,d) for (u,d) in batch))

        # Build mapping and rewrite HTML (also handle CSS @import)
        mapping = {u: p for (u, p) in saved_assets.items()}
        for u, p in page_html_paths.items():
            mapping[u] = p

        # Optionally follow CSS @import inside saved stylesheets
        if cfg.inline_css_imports:
            css_files = [p for p in saved_assets.values() if p.suffix.lower() in (".css",)]
            for css_path in css_files:
                try:
                    text = css_path.read_text(encoding="utf-8", errors="ignore")
                    imports = CSS_IMPORT_RE.findall(text)
                    changed = False
                    for u in imports:
                        absu = urllib.parse.urljoin("file:///"+str(css_path), u)
                        # turn file-based absolute into proper web absolute if needed
                        if not (u.startswith("http://") or u.startswith("https://")):
                            # try to resolve relative to original host path; skip if unknown
                            continue
                        if (cfg.all_host_assets or urllib.parse.urlparse(absu).hostname in allowed_hosts) and (u not in mapping):
                            # fetch and save
                            # NOTE: we don't have original referer; rely on prior capture or skip
                            pass
                    # (We keep CSS as-is; Playwright's response handler will have captured imported CSS if requested by page)
                except Exception:
                    pass  # non-fatal

        for u, p in page_html_paths.items():
            txt = p.read_text(encoding="utf-8", errors="ignore")
            new_txt = rewrite_urls_in_text(txt, mapping, p, cfg.strip_csp)
            if new_txt != txt:
                p.write_text(new_txt, encoding="utf-8")

        # Simple index
        index_path = pathlib.Path(cfg.out_dir) / "index.html"
        ensure_parent(index_path)
        with open(index_path, "w", encoding="utf-8") as f:
            f.write("<h1>Local Mirror</h1><ul>\n")
            for u, p in sorted(page_html_paths.items()):
                rel = os.path.relpath(p, start=out_dir)
                f.write(f'<li><a href="{rel}">{u}</a></li>\n')
            f.write("</ul>\n")

        await browser.close()

def run_mirror(cfg: MirrorConfig):
    asyncio.run(run_mirror_async(cfg))


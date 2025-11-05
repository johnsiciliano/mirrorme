# mirrorme

A Playwright-powered website mirrorer that renders pages like a real browser, downloads **all assets** (HTML, CSS, JS, images, fonts), and rewrites links to **relative** paths for reliable offline viewing.

- Handles JS-rendered sites and CDN/image-proxy setups that often 403 classic crawlers
- Honors cookies/storage state (optional) to mirror authenticated sites you own
- Keeps everything local and browsable from `index.html`
- Works for gamma sites

## Install

```bash
cd mirrorme
./install.sh
# then:
source .venv/bin/activate
```

Example usage
```bash
mirrorme "https://site.gamma.site/" \
  -o site_mirror \
  -d 4 \
  -H cdn.gamma.app -H imgproxy.gamma.app \
  --all-host-assets \
  --assets-mode pages \
  --assets-dir assets \
  --strip-csp --scroll --wait-after-load-ms 1200
```

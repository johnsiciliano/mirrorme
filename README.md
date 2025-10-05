# mirrorme

A Playwright-powered website mirrorer that renders pages like a real browser, downloads **all assets** (HTML, CSS, JS, images, fonts), and rewrites links to **relative** paths for reliable offline viewing.

- Handles JS-rendered sites and CDN/image-proxy setups that often 403 classic crawlers
- Honors cookies/storage state (optional) to mirror authenticated sites you own
- Keeps everything local and browsable from `index.html`

## Install

```bash
git clone https://github.com/yourname/mirrorme.git
cd mirrorme
./install.sh
# then:
source .venv/bin/activate


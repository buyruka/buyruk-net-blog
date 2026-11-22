#!/usr/bin/env python3
"""Make sure every post and page also exists at its own address.

wget saves a page under the address where it first found it. When that address was only a
redirect (for example a relative link that WordPress redirected to the real post), the real
address is never saved. Each WordPress post names its real address in <link rel="canonical">,
so copy the page there when nothing is there yet.

Settings (environment variables): SITE (default: site), HOSTS (comma-separated host names).
"""
import os
import re
import shutil
import urllib.parse
from pathlib import Path

SITE = Path(os.environ.get('SITE', 'site'))
HOSTS = {h.strip() for h in os.environ.get('HOSTS', '').split(',') if h.strip()}
CANON = re.compile(r'<link\b[^>]*\brel=["\']canonical["\'][^>]*>', re.I)
HREF = re.compile(r'\bhref=["\']([^"\']+)["\']', re.I)

redirected = set()
rf = SITE / '_redirects'
if rf.exists():
    for line in rf.read_text().splitlines():
        if line.strip() and not line.startswith('#'):
            redirected.add(line.split()[0])

placed = []
for p in sorted(SITE.rglob('*.html')):
    m = CANON.search(p.read_text(encoding='utf-8', errors='surrogateescape')[:30000])
    h = HREF.search(m.group(0)) if m else None
    if not h:
        continue
    u = urllib.parse.urlsplit(h.group(1))
    path = urllib.parse.unquote(u.path)
    if u.hostname not in HOSTS or u.query or not path.endswith('/') or path in redirected:
        continue
    target = SITE / path.lstrip('/') / 'index.html'
    if target.exists():
        continue
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(p, target)
    placed.append(f'{p.relative_to(SITE).as_posix()} -> {path}')

print(f'placed {len(placed)} pages at their own address')
for x in placed:
    print('  ' + x)
report = Path('crawl-report.md')
if report.exists() and placed:
    report.write_text(report.read_text().rstrip('\n') + f'\n- pages copied to their own address (saved elsewhere by wget): {len(placed)}\n')

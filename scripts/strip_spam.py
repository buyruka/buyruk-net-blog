#!/usr/bin/env python3
"""Clean comment spam out of the static WordPress archive in site/.

Settings (environment variables):
  SITE                 folder with the static site (default: site)
  SPAM_MIN_COMMENT_ID  remove every comment whose id is >= this number. Comment ids only go up,
                       so this removes everything posted after a cut-off (here: after the last post).
  DROP_WIDGETS         comma-separated widget ids to remove from every page, e.g. recent-comments
  REMOVE_COMMENT_FORM  1 = remove the "leave a reply" form (it cannot work on a static site)
  DROP_STATS_MEMBERS   1 = remove the WP-Stats "Comments' Members Stats" list (mostly spam names)

Comment pages (/comment-page-N/) left with no comments are deleted and redirected to their post.
The original comments are all still in the database backup.
"""
import os
import re
from pathlib import Path

SITE = Path(os.environ.get('SITE', 'site'))
MIN_ID = int(os.environ['SPAM_MIN_COMMENT_ID']) if os.environ.get('SPAM_MIN_COMMENT_ID') else None
WIDGETS = [w.strip() for w in os.environ.get('DROP_WIDGETS', '').split(',') if w.strip()]
FORM = os.environ.get('REMOVE_COMMENT_FORM') == '1'
STATS = os.environ.get('DROP_STATS_MEMBERS') == '1'

ARTICLE = re.compile(r'<article id="comment-(\d+)"')
TOKENS = re.compile(r'<ul class="children">|</ul><!-- \.children -->|</li><!-- #comment-## -->')
RESPOND = re.compile(r'<div id="respond"[^>]*>.*?</div><!-- #respond -->', re.S)
LEAVE_RESPONSE = re.compile(r'<p>\s*You can\s*<a href="#respond">leave a response</a>'
                            r'(?:[^<]|<a\b[^>]*>[^<]*</a>)*?from your own site\.\s*</p>')
STATS_RE = re.compile(r'<h2>Comments&#8217; Members Stats</h2>.*?</ol>', re.S)
COMMENT_PAGE = re.compile(r'^(.*/)comment-page-\d+/index\.html$')
MARKER = '<!--comments-section-removed-->'


def remove_element(h, start, tag):
    """Remove the element whose start tag begins at `start`, counting nested tags of the same name."""
    tags = re.compile(r'<(/?)' + tag + r'\b[^>]*>', re.I)
    depth = 0
    for t in tags.finditer(h, start):
        depth += -1 if t.group(1) else 1
        if depth == 0:
            return h[:start] + h[t.end():], True
    return h, False  # unbalanced: leave the page alone


def drop_by_id(h, id_pattern):
    count = 0
    while True:
        m = re.search(r'<(section|li|div|aside)\b[^>]*\bid="' + id_pattern + r'"', h)
        if not m:
            return h, count
        h, ok = remove_element(h, m.start(), m.group(1))
        if not ok:
            return h, count
        count += 1


def strip_comments(h):
    out, pos, removed = [], 0, 0
    for m in ARTICLE.finditer(h):
        if m.start() < pos or int(m.group(1)) < MIN_ID:
            continue
        depth, end = 0, None
        for t in TOKENS.finditer(h, m.end()):
            tok = t.group(0)
            if tok.startswith('<ul'):
                depth += 1
            elif tok.startswith('</ul'):
                depth -= 1
                if depth < 0:
                    break
            elif depth == 0:
                end = t.end()
                break
        if end is None:
            continue  # could not find where this comment ends; keep it rather than break the page
        removed += len(ARTICLE.findall(h, m.start(), end))
        out.append(h[pos:m.start()])
        pos = end
    out.append(h[pos:])
    return ''.join(out), removed


stats = dict(comments=0, widgets=0, forms=0, member_lists=0, emptied_sections=0, pages_deleted=0)
redirects = []
for p in sorted(SITE.rglob('*.html')):
    h = orig = p.read_text(encoding='utf-8', errors='surrogateescape')
    for w in WIDGETS:
        h, n = drop_by_id(h, re.escape(w) + r'-\d+')
        stats['widgets'] += n
    if STATS:
        h, n = STATS_RE.subn('', h)
        stats['member_lists'] += n
    if FORM:
        h, n = RESPOND.subn('', h)
        stats['forms'] += n
        h, _ = drop_by_id(h, 'respond')  # the theme's now-empty wrapper around the form
        h = LEAVE_RESPONSE.sub('', h)    # "You can leave a response, or trackback from your own site."
    if MIN_ID is not None and ARTICLE.search(h):
        h, n = strip_comments(h)
        stats['comments'] += n
        if n and not ARTICLE.search(h):
            rel = p.relative_to(SITE).as_posix()
            cp = COMMENT_PAGE.match(rel)
            if cp:  # a comment page that only held spam: send visitors to the post itself
                p.unlink()
                stats['pages_deleted'] += 1
                redirects.append(f'/{rel[:-len("index.html")]} /{cp.group(1)} 301')
                continue
            m = re.search(r'<aside\b[^>]*\bid="comments"', h)  # the now-empty "N Comments" section
            if m:
                h, ok = remove_element(h, m.start(), 'aside')
                if ok:
                    h = h[:m.start()] + MARKER + h[m.start():]
                    stats['emptied_sections'] += 1
    if h != orig:
        p.write_text(h, encoding='utf-8', errors='surrogateescape')

# Posts whose newest comments were all spam: link the older comment pages that are left.
for p in sorted(SITE.rglob('index.html')):
    h = p.read_text(encoding='utf-8', errors='surrogateescape')
    if MARKER not in h:
        continue
    pages = sorted((int(d.name.split('-')[-1]) for d in p.parent.glob('comment-page-*')
                    if (d / 'index.html').exists()))
    url = '/' + p.parent.relative_to(SITE).as_posix() + '/'
    nav = ''
    if pages:
        links = ' &middot; '.join(f'<a href="{url}comment-page-{n}/#comments">{n}</a>' for n in pages)
        nav = f'<aside id="comments"><h3>Comments</h3><p>Earlier comments, page: {links}</p></aside>'
    p.write_text(h.replace(MARKER, nav), encoding='utf-8', errors='surrogateescape')

if redirects:
    rf = SITE / '_redirects'
    existing = rf.read_text() if rf.exists() else ''
    rf.write_text(existing.rstrip('\n') + ('\n' if existing else '') + '\n'.join(redirects) + '\n')

remaining = sum(len(ARTICLE.findall(p.read_text(encoding='utf-8', errors='surrogateescape')))
                for p in SITE.rglob('*.html'))
summary = (f"- spam clean-up: removed {stats['comments']} comments (id >= {MIN_ID}), "
           f"{stats['widgets']} recent-comments widgets, {stats['forms']} comment forms, "
           f"{stats['member_lists']} stats member lists, {stats['emptied_sections']} empty comment sections; "
           f"deleted {stats['pages_deleted']} spam-only comment pages (redirected to their post); "
           f"comments still shown (counted per page): {remaining}")
print(summary)
report = Path('crawl-report.md')
if report.exists():
    report.write_text(report.read_text().rstrip('\n') + '\n' + summary + '\n')

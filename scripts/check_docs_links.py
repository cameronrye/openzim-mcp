#!/usr/bin/env python3
"""Link checker for the built docs site and the repo-root markdown.

Two failure modes this exists to catch, both of which shipped to production:

* **Internal links and heading anchors.** Astro will happily build a page whose
  ``[text](/openzim-mcp/docs/nope/)`` goes nowhere, and an ``#anchor`` pointing
  at a heading that was renamed is invisible until a reader clicks it.
* **External links to things that no longer exist.** The site offered GitHub
  Discussions as its primary support channel on four pages while Discussions
  was disabled on the repository, and advertised a ``.well-known/security.txt``
  that GitHub Pages cannot serve from a project path.

Internal checking is offline and deterministic, so it always runs. External
checking needs the network and is opt-in via ``--external``; it fails only on a
definitive 4xx, because a 5xx or a timeout says something about the remote host
rather than about this repository.

Usage::

    python scripts/check_docs_links.py                      # internal only
    python scripts/check_docs_links.py --external           # also probe URLs
    python scripts/check_docs_links.py --dist website/dist
"""

from __future__ import annotations

import argparse
import html
import os
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import unquote, urldefrag

REPO = Path(__file__).resolve().parents[1]
DEFAULT_DIST = REPO / "website" / "dist"
BASE = "/openzim-mcp"

HREF_RE = re.compile(r'href="([^"]+)"')
ID_RE = re.compile(r'id="([^"]+)"')
# Markdown URLs may contain balanced parentheses — Wikipedia's
# ``ZIM_(file_format)`` is the case in this repo — so a lazy ``[^)]+`` would
# truncate the URL and then report the truncation as a 404.
MD_LINK_RE = re.compile(r"\[[^\]]*\]\((https?://(?:[^()\s]|\([^()\s]*\))+)\)")

NON_HTTP_SCHEMES = ("mailto:", "javascript:", "tel:", "data:", "#")

# Hosts that rate-limit or block unauthenticated HEAD/GET from CI runners.
# Skipped rather than silently passed, and reported in the summary.
EXTERNAL_SKIP_HOSTS = ("badge.fury.io", "img.shields.io", "codecov.io")

USER_AGENT = (
    "openzim-mcp-docs-linkcheck/1.0 (+https://github.com/cameronrye/openzim-mcp)"
)


def _url_path(dist: Path, path: Path) -> str:
    rel = path.relative_to(dist).as_posix()
    if rel.endswith("index.html"):
        rel = rel[: -len("index.html")]
    return f"{BASE}/{rel}".replace("//", "/")


def check_internal(dist: Path) -> tuple[list[str], int]:
    """Return (problems, number of links checked)."""
    if not dist.is_dir():
        return [f"dist directory not found: {dist} (run `npm run build` first)"], 0

    pages = {p: p.read_text(encoding="utf-8") for p in dist.rglob("*.html")}
    if not pages:
        return [f"no HTML found under {dist}"], 0

    ids = {_url_path(dist, p): set(ID_RE.findall(src)) for p, src in pages.items()}
    known = set(ids)

    assets: set[str] = set()
    for p in dist.rglob("*"):
        if p.is_file():
            assets.add(
                _url_path(dist, p)
                if p.name == "index.html"
                else f"{BASE}/{p.relative_to(dist).as_posix()}"
            )

    problems: list[str] = []
    checked = 0
    for page, src in pages.items():
        here = _url_path(dist, page)
        for raw_href in HREF_RE.findall(src):
            raw = html.unescape(raw_href)
            if raw.startswith(NON_HTTP_SCHEMES[:-1]) or raw.startswith(
                ("http://", "https://")
            ):
                continue
            checked += 1
            target, frag = urldefrag(raw)
            if not target:
                if frag and frag not in ids.get(here, set()):
                    problems.append(f"{here} -> {raw} (no such anchor on this page)")
                continue
            if not target.startswith("/"):
                base_dir = os.path.dirname(here.rstrip("/") + "/x")
                target = os.path.normpath(os.path.join(base_dir, target))
                if raw.endswith("/") and not target.endswith("/"):
                    target += "/"
            target = unquote(target)
            if target in known:
                if frag and frag not in ids[target]:
                    problems.append(f"{here} -> {raw} (no such anchor on target)")
            elif target not in assets:
                problems.append(f"{here} -> {raw} (no such page)")
    return problems, checked


def _collect_external(dist: Path) -> dict[str, set[str]]:
    urls: dict[str, set[str]] = {}
    for page in dist.rglob("*.html"):
        here = _url_path(dist, page)
        for raw in HREF_RE.findall(page.read_text(encoding="utf-8")):
            url = html.unescape(raw)
            if url.startswith(("http://", "https://")):
                urls.setdefault(url, set()).add(here)
    for name in ("README.md", "CONTRIBUTING.md", "SECURITY.md", "CODE_OF_CONDUCT.md"):
        md = REPO / name
        if md.is_file():
            for url in MD_LINK_RE.findall(md.read_text(encoding="utf-8")):
                urls.setdefault(url, set()).add(name)
    return urls


def _probe(url: str, timeout: float) -> int | None:
    """Return an HTTP status, or None when the host could not be reached."""
    for method in ("HEAD", "GET"):
        req = urllib.request.Request(  # noqa: S310 - fixed https scheme, see caller
            url, method=method, headers={"User-Agent": USER_AGENT}
        )
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310
                return int(resp.status)
        except urllib.error.HTTPError as exc:
            if exc.code in (403, 405) and method == "HEAD":
                continue  # some hosts refuse HEAD; retry as GET
            return int(exc.code)
        except (urllib.error.URLError, TimeoutError, OSError):
            return None
    return None


def check_external(dist: Path, timeout: float) -> tuple[list[str], list[str], int]:
    """Return (problems, skipped, number probed)."""
    problems: list[str] = []
    skipped: list[str] = []
    probed = 0
    for url, sources in sorted(_collect_external(dist).items()):
        if not url.startswith("https://"):
            problems.append(f"{url} (non-HTTPS; referenced by {sorted(sources)[0]})")
            continue
        if any(host in url for host in EXTERNAL_SKIP_HOSTS):
            skipped.append(url)
            continue
        probed += 1
        status = _probe(url, timeout)
        if status is None:
            skipped.append(f"{url} (unreachable — treated as transient)")
        elif 400 <= status < 500:
            problems.append(f"{url} -> HTTP {status} (from {sorted(sources)[0]})")
    return problems, skipped, probed


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dist", type=Path, default=DEFAULT_DIST)
    ap.add_argument("--external", action="store_true", help="also probe external URLs")
    ap.add_argument("--timeout", type=float, default=20.0)
    args = ap.parse_args()

    internal, n_internal = check_internal(args.dist)
    print(f"internal links checked: {n_internal}")
    for problem in internal:
        print(f"  BROKEN  {problem}")

    external: list[str] = []
    if args.external:
        external, skipped, n_external = check_external(args.dist, args.timeout)
        print(f"external URLs probed: {n_external}")
        for problem in external:
            print(f"  BROKEN  {problem}")
        for note in skipped:
            print(f"  skipped {note}")

    total = len(internal) + len(external)
    if total:
        print(f"\n{total} broken link(s).")
        return 1
    print("\nAll links resolve.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

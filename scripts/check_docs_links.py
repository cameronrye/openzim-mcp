#!/usr/bin/env python3
"""Link checker for the built docs site and the repo's own markdown.

Three failure modes this exists to catch. The first two shipped to production;
the third is a gap in this checker itself — nothing is known to have gone wrong
through it, and nothing would have noticed if it had:

* **Internal links and heading anchors.** Astro will happily build a page whose
  ``[text](/openzim-mcp/docs/nope/)`` goes nowhere, and an ``#anchor`` pointing
  at a heading that was renamed is invisible until a reader clicks it.
* **External links to things that no longer exist.** The site offered GitHub
  Discussions as a support channel on six pages while Discussions was
  disabled on the repository, and advertised a ``.well-known/security.txt``
  that GitHub Pages cannot serve from a project path.
* **Links to our own site written absolutely.** ``README.md`` points readers at
  ``https://cameronrye.github.io/openzim-mcp/docs/...`` throughout. Such a URL
  used to fall between the two halves below and be checked by neither: the
  internal pass skipped every absolute href, and the external pass skipped
  every URL under the site's own base on the assumption that the internal pass
  had already covered it. A wrong one — a page renamed, or a path typed by
  hand — would have been reported by nothing. No such link is known to have
  shipped; the point is that one could have. Both halves now resolve them
  against the build, sharing one index and one matcher so they cannot disagree.

Internal checking is offline and deterministic, so it always runs. External
checking needs the network and is opt-in via ``--external``; it fails only on a
definitive 4xx, because a 5xx or a timeout says something about the remote host
rather than about this repository. Resolving a link to our own site is offline
either way — it is answered by the build, never by an HTTP probe.

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
from typing import NamedTuple
from urllib.parse import unquote, urldefrag, urlsplit

REPO = Path(__file__).resolve().parents[1]
DEFAULT_DIST = REPO / "website" / "dist"
BASE = "/openzim-mcp"

HREF_RE = re.compile(r'href="([^"]+)"')
ID_RE = re.compile(r'id="([^"]+)"')

# A fenced code block, opening or closing. Everything between a pair of these
# is blanked before any of MARKDOWN_URL_RES runs, so a URL in a shell
# transcript or a config sample is never mistaken for a link this repo makes.
# Today that blanking removes nothing: every URL currently written inside a
# fence is bare, and bare URLs are already excluded below. It earns its place
# on the sample that is written as a markdown link or an ``<a href>`` — the
# forms below cannot tell that one from a real one, and this can.
MD_FENCE_RE = re.compile(r"^\s{0,3}(?:```|~~~)")

# The link forms a URL can take in this repo's markdown. All four are needed:
# matching only the first left README.md's own most prominent docs pointer —
# written as an autolink — collected by nothing.
#
# NOT collected, deliberately: a bare unbracketed URL in prose. CommonMark does
# not linkify one, GitHub's renderer does, and telling the two apart from a
# regex is guesswork that costs false positives on every URL this repo writes
# inside backticks. Write a URL you want checked as a link, not as bare text.
MARKDOWN_URL_RES = (
    # ``[text](url)``. Markdown URLs may contain balanced parentheses —
    # Wikipedia's ``ZIM_(file_format)`` is the case in this repo — so a lazy
    # ``[^)]+`` would truncate the URL and report the truncation as a 404.
    re.compile(r"\[[^\]]*\]\((https?://(?:[^()\s]|\([^()\s]*\))+)\)"),
    # ``<url>`` autolink. README.md's "Full documentation lives at" pointer,
    # the most prominent docs link it has, is written this way.
    re.compile(r"<(https?://[^<>\s]+)>"),
    # ``[label]: url`` reference definition, optionally angle-bracketed.
    re.compile(r"^ {0,3}\[[^\]]+\]:\s*<?(https?://[^>\s]+?)>?\s*$", re.M),
    # Raw HTML in markdown: README.md's logo and badge block is written as
    # ``<a href>`` and ``<img src>``, which none of the three forms above
    # match. Inline links still outnumber them in that file; the point is not
    # that they are the majority, it is that nothing else collects them.
    re.compile(r'(?:href|src)="(https?://[^"]+)"'),
)

# Repo markdown that is an input to this check. The four at the root are the
# repository's front-matter documents — GitHub renders README.md on the project
# page and surfaces the other three through the community profile and their own
# tabs; docs/ holds operator notes that are not
# part of the built site but link into it — docs/extras-reranker.md and
# docs/roadmap.md each carry a site URL. These live outside website/, so
# website-ci.yml lists them in its `paths:` trigger: without that, a PR
# touching only README.md never runs the job that reads it. Add a path here
# and add it there too.
MARKDOWN_ROOT_FILES = (
    "README.md",
    "CONTRIBUTING.md",
    "SECURITY.md",
    "CODE_OF_CONDUCT.md",
)
MARKDOWN_GLOBS = ("docs/*.md",)

NON_HTTP_SCHEMES = ("mailto:", "javascript:", "tel:", "data:", "#")

# A link to the reader's own machine — CONTRIBUTING.md tells contributors to
# open the dev server at <http://localhost:4321/openzim-mcp/>. There is nothing
# to probe, and its http:// is correct rather than a downgrade to flag.
LOCAL_HOSTS = ("localhost", "127.0.0.1", "0.0.0.0", "[::1]", "::1")

# The site's own absolute URL. Every page emits its own canonical link, and
# cross-page links are sometimes written absolute, so probing these against the
# live deployment asks "is this page already published?" — which is false for
# every page a PR adds. That made the check structurally red on exactly the
# change it most needed to pass. So these are never probed; they are resolved
# against the build, by _resolve_path() on both sides of the checker.
SITE_ORIGIN = "https://cameronrye.github.io"
SITE_BASE = f"{SITE_ORIGIN}{BASE}"

# "Edit this page on GitHub" links point at blob/main for a file that, on a
# branch adding it, is not on main yet. Resolve against the working tree.
EDIT_LINK_PREFIX = "https://github.com/cameronrye/openzim-mcp/blob/main/"

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


class NoBuild(Exception):
    """website/dist is missing or empty. Both halves of the checker need it."""


class SiteIndex(NamedTuple):
    """The built site, indexed once so both halves resolve links identically.

    Before this existed, check_internal() built these maps privately and
    check_external() had no way to reach them, so it skipped every URL under
    SITE_BASE on the assumption that the internal pass had already proven it.
    That was true for relative hrefs in built HTML and false for absolute
    site URLs — most of all the ones in the repo's markdown, which the
    internal pass never reads at all.

    * ``sources`` — page URL path -> the HTML text of that page.
    * ``ids`` — page URL path -> the set of ``id=""`` values on that page.
    * ``pages`` — every page URL path (the keys of ``ids``).
    * ``assets`` — every file in the build as a URL path, HTML included.
    """

    sources: dict[str, str]
    ids: dict[str, set[str]]
    pages: set[str]
    assets: set[str]


def build_index(dist: Path) -> SiteIndex:
    """Index the built site. Raises NoBuild when there is nothing to index."""
    if not dist.is_dir():
        raise NoBuild(f"dist directory not found: {dist} (run `npm run build` first)")

    sources = {
        _url_path(dist, p): p.read_text(encoding="utf-8") for p in dist.rglob("*.html")
    }
    if not sources:
        raise NoBuild(f"no HTML found under {dist}")

    ids = {here: set(ID_RE.findall(src)) for here, src in sources.items()}

    assets: set[str] = set()
    for p in dist.rglob("*"):
        if p.is_file():
            assets.add(
                _url_path(dist, p)
                if p.name == "index.html"
                else f"{BASE}/{p.relative_to(dist).as_posix()}"
            )

    return SiteIndex(sources=sources, ids=ids, pages=set(ids), assets=assets)


def _site_target(url: str) -> tuple[str, str] | None:
    """Split a URL of *our own* site into (site path, fragment), else None.

    Two things this gets right that a bare ``url.startswith(SITE_BASE)`` did
    not. The prefix tested is ``SITE_BASE + "/"``, so a sibling project on the
    same GitHub Pages user site — ``…github.io/openzim-mcp-other/`` — reads as
    somebody else's URL to probe rather than as a page of ours gone missing.
    And the query string is dropped before matching, because a static build has
    no query strings in its filenames: keeping one would turn a working link
    into a phantom "no such page".
    """
    rest, frag = urldefrag(url)
    rest = rest.partition("?")[0]
    if not rest.startswith(SITE_BASE + "/"):
        return None
    return rest[len(SITE_ORIGIN) :], frag


def _resolve_path(target: str, frag: str, index: SiteIndex) -> str | None:
    """Match one absolute site path plus fragment against the build.

    Returns a short reason the link does not resolve, or None when it does.
    This is the whole of the matching rule — percent-decoding included — and
    both halves of the checker call it, so neither can drift into accepting a
    link the other rejects. Matching is exact: ``/openzim-mcp/docs`` does not
    match the built ``/openzim-mcp/docs/``, because the trailing slash is what
    the build actually emits and a redirect is not a link that resolves.
    """
    target = unquote(target)
    if target in index.pages:
        if frag and frag not in index.ids[target]:
            return "no such anchor on target"
        return None
    if target in index.assets:
        return None
    return "no such page"


def _resolve_href(here: str, link: str, index: SiteIndex) -> str | None:
    """Resolve one href as written on the page at ``here``.

    Handles the two forms an absolute site URL never takes — a bare
    ``#fragment`` and a page-relative path — then defers to _resolve_path().
    """
    target, frag = urldefrag(link)
    if not target:
        if frag and frag not in index.ids.get(here, set()):
            return "no such anchor on this page"
        return None
    if not target.startswith("/"):
        base_dir = os.path.dirname(here.rstrip("/") + "/x")
        target = os.path.normpath(os.path.join(base_dir, target))
        # normpath eats a trailing slash; the build's page paths carry one.
        if link.endswith("/") and not target.endswith("/"):
            target += "/"
    return _resolve_path(target, frag, index)


def check_internal(index: SiteIndex) -> tuple[list[str], int]:
    """Return (problems, number of links checked).

    Checks every href in the built HTML that points inside the site: relative
    paths, same-page ``#anchor``s, and absolute URLs under SITE_BASE. Hrefs to
    another host are left to check_external(); the first four NON_HTTP_SCHEMES
    (``mailto:``, ``javascript:``, ``tel:``, ``data:``) are checked by neither
    half — the fifth, ``#``, is the same-page anchor case, which is checked
    here. This reads built HTML only: the site URLs in the repo's markdown are
    check_external()'s, and only its.
    """
    problems: list[str] = []
    checked = 0
    for here, src in index.sources.items():
        for raw_href in HREF_RE.findall(src):
            raw = html.unescape(raw_href)
            site = _site_target(raw)
            if site is not None:
                # An absolute link to our own site is an internal link written
                # the long way — every page's canonical <link> is one, and
                # hand-written cross-page links sometimes are. Resolving it
                # here keeps it in the offline, always-on pass instead of
                # leaving it to a network pass that is opt-in.
                reason = _resolve_path(site[0], site[1], index)
            elif raw.startswith(NON_HTTP_SCHEMES[:-1]) or raw.startswith(
                ("http://", "https://")
            ):
                continue
            else:
                reason = _resolve_href(here, raw, index)
            checked += 1
            if reason:
                problems.append(f"{here} -> {raw} ({reason})")
    return problems, checked


def _markdown_files() -> list[tuple[str, Path]]:
    """(display name, path) for every repo markdown file this check reads."""
    found = [(name, REPO / name) for name in MARKDOWN_ROOT_FILES]
    for pattern in MARKDOWN_GLOBS:
        found += [
            (p.relative_to(REPO).as_posix(), p) for p in sorted(REPO.glob(pattern))
        ]
    return [(name, path) for name, path in found if path.is_file()]


def _outside_fences(text: str) -> str:
    """``text`` with every line of every fenced code block replaced by ""."""
    kept: list[str] = []
    in_fence = False
    for line in text.splitlines():
        if MD_FENCE_RE.match(line):
            in_fence = not in_fence
            kept.append("")
        else:
            kept.append("" if in_fence else line)
    return "\n".join(kept)


def _collect_external(index: SiteIndex) -> dict[str, set[str]]:
    """Absolute URL -> the pages and files that reference it."""
    urls: dict[str, set[str]] = {}
    for here, src in index.sources.items():
        for raw in HREF_RE.findall(src):
            url = html.unescape(raw)
            if url.startswith(("http://", "https://")):
                urls.setdefault(url, set()).add(here)
    for name, md in _markdown_files():
        prose = _outside_fences(md.read_text(encoding="utf-8"))
        for pattern in MARKDOWN_URL_RES:
            for url in pattern.findall(prose):
                urls.setdefault(html.unescape(url), set()).add(name)
    return urls


def _markdown_anchors(path: Path) -> set[str]:
    """Heading anchors GitHub would generate for a markdown file.

    GitHub's slugger: strip inline links to their text, lowercase, drop every
    character that is not a word char, space or hyphen, then replace each space
    with one hyphen — so "Migrating from v1.x / v2 beta" becomes
    "migrating-from-v1x--v2-beta" (two hyphens, because "/" is removed and both
    surrounding spaces survive). Collapsing runs of spaces here would produce a
    single hyphen and report a working link as broken.
    """
    anchors: set[str] = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        m = re.match(r"^#{1,6}\s+(.*)$", line)
        if not m:
            continue
        text = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", m.group(1)).strip().lower()
        slug = re.sub(r"[^\w\s-]", "", text).replace(" ", "-")
        candidate, n = slug, 0
        while candidate in anchors:  # GitHub suffixes duplicates -1, -2, ...
            n += 1
            candidate = f"{slug}-{n}"
        anchors.add(candidate)
    return anchors


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


def check_external(
    index: SiteIndex, timeout: float
) -> tuple[list[str], list[str], int]:
    """Return (problems, skipped, number probed).

    Sources: every absolute ``href`` in the built HTML, plus the URLs in the
    repo markdown that _markdown_files() lists — collected from the four link
    forms in MARKDOWN_URL_RES (inline, autolink, reference definition, raw
    ``href``/``src`` attribute).

    Not covered, so that nobody reads more into a green run than it means: a
    bare unbracketed URL in markdown prose; anything inside a fenced code
    block; and, in the built HTML, an absolute ``src`` — HREF_RE reads
    ``href`` alone, so an ``<img src>`` pointing at another host is collected
    by neither half of this checker. A URL written any of those ways is
    checked by nothing at all.

    Only the URLs that reach the ``_probe`` call at the bottom are counted as
    probed: links to our own site are resolved against the build, "edit this
    page" links against the working tree, and loopback URLs and the
    rate-limiting hosts are listed as skipped.
    """
    problems: list[str] = []
    skipped: list[str] = []
    probed = 0
    for url, sources in sorted(_collect_external(index).items()):
        site = _site_target(url)
        if site is not None:
            # Our own page, resolved against the build rather than probed: the
            # live site lags by a deploy, so an HTTP probe would ask "is this
            # page already published?" — false for every page a PR adds.
            # check_internal() covers the hrefs in built HTML but not the repo
            # markdown, which only this function reads; before both halves
            # shared this matcher, a site URL written there was resolved by
            # neither. Same matcher as check_internal(), so the two cannot
            # disagree about what resolves.
            reason = _resolve_path(site[0], site[1], index)
            if reason:
                problems.append(f"{url} ({reason}; referenced by {sorted(sources)[0]})")
            continue
        if (urlsplit(url).hostname or "") in LOCAL_HOSTS:
            skipped.append(f"{url} (loopback — nothing to probe)")
            continue
        if not url.startswith("https://"):
            problems.append(f"{url} (non-HTTPS; referenced by {sorted(sources)[0]})")
            continue
        if url.startswith(EDIT_LINK_PREFIX):
            # A repo file. Check the working tree, not github.com — on a branch
            # adding the file, main does not have it yet. This is also a
            # STRONGER check than an HTTP probe: github.com returns 200 for a
            # blob URL with a heading anchor that does not exist, so a stale
            # `#anchor` is invisible over the wire but caught here.
            rel, _, frag = url[len(EDIT_LINK_PREFIX) :].partition("#")
            target = REPO / unquote(rel)
            if not target.is_file():
                problems.append(
                    f"{url} (no such file in this repo: {rel}; "
                    f"referenced by {sorted(sources)[0]})"
                )
            elif frag and target.suffix in (".md", ".mdx"):
                if frag not in _markdown_anchors(target):
                    problems.append(
                        f"{url} (no heading anchor #{frag} in {rel}; "
                        f"referenced by {sorted(sources)[0]})"
                    )
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

    # Indexed once and shared: both halves resolve in-site links against the
    # same page, anchor and asset maps, so neither can accept a link the other
    # rejects. Without a build there is nothing for either half to resolve
    # against, so stop rather than report every in-site link as broken.
    try:
        index = build_index(args.dist)
    except NoBuild as exc:
        print("internal links checked: 0")
        print(f"  BROKEN  {exc}")
        print("\n1 broken link(s).")
        return 1

    internal, n_internal = check_internal(index)
    print(f"internal links checked: {n_internal}")
    for problem in internal:
        print(f"  BROKEN  {problem}")

    external: list[str] = []
    if args.external:
        external, skipped, n_external = check_external(index, args.timeout)
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

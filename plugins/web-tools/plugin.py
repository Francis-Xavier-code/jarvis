"""web-tools: web search + page fetch for the assistant.

  * web.search(query, n?) - search the web, return title/url/snippet list
  * web.fetch(url, max_chars?) - fetch a page and extract readable text

Zero API key: the default search backend is DuckDuckGo\'s HTML endpoint.
A custom search URL can be configured via config [web] search_url (a
GET endpoint returning HTML with result links/snippets is expected).

Safety: only http(s) URLs are fetched, with a timeout and a size cap. Both
tools are read-only, so no confirmation is required - but note that fetching
arbitrary URLs can reach local-network services, so treat results with care.
"""
from __future__ import annotations

import html as html_mod
import re
import urllib.parse

try:
    import requests  # soft dependency
except ImportError:  # pragma: no cover
    requests = None

from jarvis.types import KernelApi

DEFAULT_SEARCH = "https://html.duckduckgo.com/html/"
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X) JARVIS/1.0"
FETCH_MAX_BYTES = 200_000


def _cfg(kernel: KernelApi, key: str, default):
    return kernel.config.get(f"web.{key}", default)


def _truncate(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[:limit] + f"\n... (truncated {len(text) - limit} chars)"


def _ddg_unwrap(href: str) -> str:
    """DuckDuckGo HTML links are redirects like /l/?uddg=<url>; extract the real one."""
    parsed = urllib.parse.urlparse(href)
    if parsed.path in ("/l/", "/l"):
        q = urllib.parse.parse_qs(parsed.query)
        return q.get("uddg", [href])[0]
    return href


def _extract_text(html: str) -> str:
    """Crude HTML -> text: drop scripts/styles, strip tags, unescape, squeeze."""
    html = re.sub(r"(?is)<(script|style|noscript)[^>]*>.*?</\1>", " ", html)
    html = re.sub(r"(?is)<br\s*/?>", "\n", html)
    html = re.sub(r"(?is)</(p|div|li|h[1-6]|tr)>", "\n", html)
    text = re.sub(r"(?s)<[^>]+>", " ", html)
    text = html_mod.unescape(text)
    return re.sub(r"[ \t\xa0]+", " ", text).strip()


def setup(kernel: KernelApi) -> None:
    @kernel.tool(
        "web.search",
        "Search the web and return a list of results (title, url, snippet) - use before answering questions about current events or unknown facts",
        {"query": {"type": "string"}, "n": {"type": "integer"}},
    )
    def web_search(query: str, n: int = 5) -> str:
        if requests is None:
            return "[web] missing dependency: pip install requests"
        if not query.strip():
            return "[web] empty query"
        n = min(max(int(n), 1), 10)
        search_url = _cfg(kernel, "search_url", DEFAULT_SEARCH)
        try:
            resp = requests.get(
                search_url,
                params={"q": query},
                headers={"User-Agent": UA},
                timeout=15,
            )
        except Exception as exc:  # noqa: BLE001
            return f"[web] search failed: {exc}"
        if resp.status_code != 200:
            return f"[web] search HTTP {resp.status_code}"
        results = _parse_results(resp.text)
        if not results:
            return "[web] no results"
        lines = []
        for title, url, snippet in results[:n]:
            lines.append(f"- {title}\n  {url}\n  {snippet or '(no snippet)'}")
        return "\n".join(lines)

    @kernel.tool(
        "web.fetch",
        "Fetch a web page (http/https only) and return its readable text - use to read the full content behind a search result",
        {"url": {"type": "string"}, "max_chars": {"type": "integer"}},
    )
    def web_fetch(url: str, max_chars: int = 4000) -> str:
        if requests is None:
            return "[web] missing dependency: pip install requests"
        if not url.startswith(("http://", "https://")):
            return "[web] only http(s) URLs are allowed"
        max_chars = min(max(int(max_chars), 500), 20000)
        try:
            resp = requests.get(
                url,
                headers={"User-Agent": UA},
                timeout=15,
                stream=True,
            )
        except Exception as exc:  # noqa: BLE001
            return f"[web] fetch failed: {exc}"
        if resp.status_code != 200:
            return f"[web] HTTP {resp.status_code}"
        try:
            raw = resp.raw.read(FETCH_MAX_BYTES + 1)
            text = raw.decode("utf-8", errors="replace")
        except Exception as exc:  # noqa: BLE001
            return f"[web] read failed: {exc}"
        body = _extract_text(text)
        if not body.strip():
            return "[web] no readable text found on page"
        return _truncate(body, max_chars)


def _parse_results(html: str) -> list["tuple[str, str, str]"]:
    """Extract (title, url, snippet) triples from DuckDuckGo HTML (or similar)."""
    out = []
    for m in re.finditer(r"(?is)<a[^>]*class=\"[^\"]*result__a[^\"]*\"[^>]*href=\"([^\"]+)\"[^>]*>(.*?)</a>", html):
        href, title = m.group(1), re.sub(r"(?s)<[^>]+>", "", m.group(2))
        out.append([html_mod.unescape(title).strip(), _ddg_unwrap(href), ""])
    snippets = re.findall(r"(?is)<a[^>]*class=\"[^\"]*result__snippet[^\"]*\"[^>]*>(.*?)</a>", html)
    for i, sn in enumerate(snippets):
        if i < len(out):
            out[i][2] = html_mod.unescape(re.sub(r"(?s)<[^>]+>", "", sn)).strip()
    return [(t, u, s) for t, u, s in out if t]


def teardown(kernel: KernelApi) -> None:
    pass
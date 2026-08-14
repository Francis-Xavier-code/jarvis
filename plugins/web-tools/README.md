# web-tools

Web **search + fetch** for the assistant — the missing "current information"
capability.

- **kind**: `tool`
- **provides**:
  - `web.search(query, n?)` — search the web, return title/url/snippet list
  - `web.fetch(url, max_chars?)` — fetch a page and return readable text

## Backend

Default search backend is **DuckDuckGo's HTML endpoint** — zero API key.
Configure a custom search URL in config.toml:

```toml
[web]
# a GET endpoint returning HTML whose links/snippets are parsed
search_url = "https://html.duckduckgo.com/html/"
```

## Safety

* Only **http(s)** URLs are fetched; 15s timeout, 200KB read cap.
* Both tools are read-only (no confirmation) — but fetching arbitrary URLs
  can reach local-network services, so treat results with care.

## Dependencies

`requests` (soft-imported; install with `pip install requests`).

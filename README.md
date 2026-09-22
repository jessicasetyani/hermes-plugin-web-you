# web-you — You.com native backend for Hermes Agent

Makes You.com a first-class `web.backend` for Hermes Agent
(`web_search` + `web_extract`), instead of going through Composio.

- Search: `GET {base}/v1/search` (`query`, `count`)
- Extract: `POST {base}/v1/contents` (`urls`, `formats: [markdown]`)
- API reference: <https://you.com/docs/api-reference/search/v1-search>

Provenance: benchmarked 22 Sep 2026 against Perplexity, Tavily and Jina
(10 search queries + 5 extract URLs, Direct REST) — You.com scored 4.52/5,
best overall. See the decision note linked below.

## Install

CLI (any machine with Hermes):

```bash
hermes plugins install jessicasetyani/hermes-plugin-web-you --enable
```

Dashboard (Nous-cloud agents, no CLI): install from this repo URL
via the dashboard plugin UI, then approve the capability consent.

## Configure

One required key, one optional endpoint override.
Key source is flexible — Bitwarden Secrets Manager or `.env`,
whichever the machine uses:

```bash
# required — put it in BWS (key name YDC_API_KEY) or ~/.hermes/.env
YDC_API_KEY=...

# optional — only when You.com moves hosts again (default is baked in)
YDC_BASE_URL=https://ydc-index.io
```

Point Hermes at it (single shared backend — the provider does
both search and extract):

```bash
hermes config set web.backend you
```

Takes effect on next session. On Nous-cloud/dashboard installs:
after plugin install + env + config, **restart the gateway and the
dashboard** before testing — the backend is picked up at process
start, and a stale process reports `no registered web search
provider 'you'` even when everything is configured correctly
(observed 22 Sep 2026).

## Verify

```bash
hermes plugins list | grep -i you   # catat KEY yang tertera (tergantung jalur install)
hermes plugins doctor <KEY>         # mis. "web/you" utk layout kategori lokal
```

Then ask the agent anything requiring fresh web info — search should
return in ~1s with 5 results.

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `403 Forbidden` on search | Wrong base host (known drift: `api.ydc-index.io` vs `ydc-index.io`) | Set `YDC_BASE_URL` to the working host, no code change |
| `429` on extract bursts | Snippets/contents rate limit | Built-in single retry; space out bulk extracts |
| `contents too thin` error | Page blocked / JS-only / empty | Honest failure by design — fall back to another backend, do not retry blindly |
| `no registered web search provider 'you'` | Stale session (started before install) | Start a new session; on cloud installs, restart gateway + dashboard first |

## Versioning

Fleet installs should pin a commit SHA (see `hermes-pack.yaml`)
so every agent runs the identical, audited copy.

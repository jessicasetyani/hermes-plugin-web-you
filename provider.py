"""You.com web search + contents — user backend plugin.

Endpoints (ref: https://you.com/docs/api-reference/search/v1-search):
  search   : GET  {base}/v1/search?query=...&count=...
  contents : POST {base}/v1/contents {urls, formats, crawl_timeout}

Env (YDC_ prefix):
  YDC_API_KEY   (required — via BWS or .env, whichever the machine uses)
  YDC_BASE_URL  (optional override in .env, default https://ydc-index.io;
                 plugin appends /v1/search and /v1/contents itself)

House rules baked in from the 22 Sep 2026 benchmark:
  - thin-guard: extract body < MIN_CHARS is an error, never a fake success
  - 429: one bounded retry, then an honest verbatim error
"""

from __future__ import annotations

import logging
import time
from typing import Any, Dict, List

import httpx

from agent.web_search_provider import WebSearchProvider, get_provider_env

logger = logging.getLogger(__name__)

_DEFAULT_BASE_URL = "https://ydc-index.io"
_KEY_DOC_URL = "https://you.com/platform"
_API_REF = "https://you.com/docs/api-reference/search/v1-search"

_MIN_EXTRACT_CHARS = 500
_SEARCH_CAP = 20

_HEADERS = {
    "User-Agent": "HermesAgent",
    "X-Title": "Hermes Agent",
}


def _api_key() -> str:
    return (get_provider_env("YDC_API_KEY") or "").strip()


def _base() -> str:
    return (get_provider_env("YDC_BASE_URL") or _DEFAULT_BASE_URL).rstrip("/")


def _missing_key_error() -> str:
    return f"YDC_API_KEY is not set. Get a key at {_KEY_DOC_URL}"


class YouWebSearchProvider(WebSearchProvider):
    """You.com search (web section) + contents (markdown extract)."""

    NAME = "you"
    DISPLAY_NAME = "You.com"
    KEY_ENV = "YDC_API_KEY"

    @property
    def name(self) -> str:
        return self.NAME

    @property
    def display_name(self) -> str:
        return self.DISPLAY_NAME

    def is_available(self) -> bool:
        # Cheap check only — no network (runs on every `hermes tools` paint).
        return bool(_api_key())

    def supports_search(self) -> bool:
        return True

    def supports_extract(self) -> bool:
        return True

    # --- search ---

    def search(self, query: str, limit: int = 5) -> Dict[str, Any]:
        api_key = _api_key()
        if not api_key:
            return {"success": False, "error": _missing_key_error()}
        count = max(1, min(int(limit or 5), _SEARCH_CAP))
        url = f"{_base()}/v1/search"
        try:
            resp = httpx.get(
                url,
                params={"query": query, "count": count},
                headers={"X-API-Key": api_key, **_HEADERS},
                timeout=25,
            )
            if resp.status_code == 429:
                time.sleep(3)
                resp = httpx.get(
                    url,
                    params={"query": query, "count": count},
                    headers={"X-API-Key": api_key, **_HEADERS},
                    timeout=25,
                )
            if resp.status_code >= 400:
                return {"success": False, "error": (resp.text or "").strip()[:300] or f"HTTP {resp.status_code}"}
            return _normalize_search(resp.json())
        except Exception as exc:  # noqa: BLE001 — httpx errors surface verbatim
            logger.warning("You.com search error: %s", exc)
            return {"success": False, "error": f"You.com search failed: {exc}"}

    # --- extract ---

    def extract(self, urls: List[str], **kwargs: Any) -> List[Dict[str, Any]]:
        api_key = _api_key()
        if not api_key:
            return [{"url": u, "title": "", "content": "", "error": _missing_key_error()} for u in urls]
        url = f"{_base()}/v1/contents"
        try:
            resp = httpx.post(
                url,
                json={"urls": list(urls), "formats": ["markdown"], "crawl_timeout": 10},
                headers={"X-API-Key": api_key, "Content-Type": "application/json", **_HEADERS},
                timeout=60,
            )
            if resp.status_code == 429:
                time.sleep(3)
                resp = httpx.post(
                    url,
                    json={"urls": list(urls), "formats": ["markdown"], "crawl_timeout": 10},
                    headers={"X-API-Key": api_key, "Content-Type": "application/json", **_HEADERS},
                    timeout=60,
                )
            if resp.status_code >= 400:
                err = (resp.text or "").strip()[:300] or f"HTTP {resp.status_code}"
                return [{"url": u, "title": "", "content": "", "error": f"You.com contents failed: {err}"} for u in urls]
            return _normalize_contents(resp.json(), list(urls))
        except Exception as exc:  # noqa: BLE001
            logger.warning("You.com extract error: %s", exc)
            return [{"url": u, "title": "", "content": "", "error": f"You.com contents failed: {exc}"} for u in urls]

    def get_setup_schema(self) -> Dict[str, Any]:
        return {
            "name": "You.com",
            "badge": "paid",
            "tag": "You.com web search + full-page contents. Requires YDC_API_KEY.",
            "env_vars": [
                {"name": "YDC_API_KEY", "label": "You.com API key", "url": _KEY_DOC_URL},
                {"name": "YDC_BASE_URL", "label": "You.com API base override (optional)", "url": _API_REF},
            ],
            "docs_url": _API_REF,
        }


def _normalize_search(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Map {results: {web: [{url,title,description}]}} to the tool envelope."""
    web = []
    try:
        items = payload.get("results", {}).get("web", [])
    except AttributeError:
        items = []
    for i, item in enumerate(items or []):
        if not isinstance(item, dict):
            continue
        web.append(
            {
                "title": str(item.get("title", "") or ""),
                "url": str(item.get("url", "") or ""),
                "description": str(item.get("description", "") or ""),
                "position": i + 1,
            }
        )
    return {"success": True, "data": {"web": web}}


def _normalize_contents(payload: Any, urls: List[str]) -> List[Dict[str, Any]]:
    """Map contents response to extract documents, with thin-guard."""
    docs: List[Dict[str, Any]] = []
    items: List[Dict[str, Any]] = []
    if isinstance(payload, list):
        items = [x for x in payload if isinstance(x, dict)]
    elif isinstance(payload, dict):
        for key in ("contents", "results", "pages"):
            if isinstance(payload.get(key), list):
                items = [x for x in payload[key] if isinstance(x, dict)]
                break
    by_url = {str(x.get("url", "")): x for x in items}
    for u in urls:
        item = by_url.get(u, {})
        title = str(item.get("title", "") or "")
        content = str(item.get("markdown", "") or item.get("content", "") or item.get("text", "") or "")
        if len(content) < _MIN_EXTRACT_CHARS:
            docs.append(
                {
                    "url": u,
                    "title": title,
                    "content": "",
                    "error": f"You.com contents too thin ({len(content)} chars < {_MIN_EXTRACT_CHARS}) — treated as failure, not success",
                }
            )
        else:
            docs.append(
                {
                    "url": u,
                    "title": title,
                    "content": content,
                    "raw_content": content,
                    "metadata": {"sourceURL": u, "title": title},
                }
            )
    return docs

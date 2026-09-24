"""Reel Radar — TMDB client with light disk cache."""

from __future__ import annotations

import hashlib
import json
import os
import re
import time
from pathlib import Path
from typing import Any

import requests
from dotenv import load_dotenv

load_dotenv()

BASE_URL = "https://api.themoviedb.org/3"
IMAGE_BASE = "https://image.tmdb.org/t/p"
CACHE_DIR = Path(__file__).resolve().parents[1] / "data" / "cache"

# Cursor/sandbox often injects a broken HTTPS_PROXY that 403s TMDB.
_NO_PROXY = {"http": None, "https": None}


def _redact(text: str) -> str:
    """Strip API keys / secrets from error surfaces."""
    text = re.sub(r"(api_key=)[^&\s]+", r"\1[REDACTED]", text, flags=re.I)
    text = re.sub(r"(Bearer\s+)\S+", r"\1[REDACTED]", text, flags=re.I)
    return text


class TMDBError(RuntimeError):
    def __init__(self, message: str):
        super().__init__(_redact(str(message)))


class TMDBClient:
    def __init__(self, api_key: str | None = None, cache_ttl: int = 60 * 60 * 12):
        self.api_key = api_key or os.getenv("TMDB_API_KEY", "").strip()
        self.cache_ttl = cache_ttl
        self.session = requests.Session()
        self.repair_session()
        CACHE_DIR.mkdir(parents=True, exist_ok=True)

    def repair_session(self) -> None:
        """Make this session independent of broken shell proxy settings."""
        self.session.trust_env = False
        self.session.proxies.clear()
        self.session.proxies.update(_NO_PROXY)

    def _cache_path(self, path: str, params: dict[str, Any]) -> Path:
        raw = path + "?" + json.dumps(params, sort_keys=True)
        digest = hashlib.sha256(raw.encode()).hexdigest()[:24]
        return CACHE_DIR / f"{digest}.json"

    def _get(self, path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        if not self.api_key:
            raise TMDBError(
                "TMDB is unavailable because TMDB_API_KEY is not configured. "
                "The saved catalog can still be used offline."
            )
        self.repair_session()
        params = dict(params or {})
        params["api_key"] = self.api_key
        cache_file = self._cache_path(path, {k: v for k, v in params.items() if k != "api_key"})
        if cache_file.exists() and (time.time() - cache_file.stat().st_mtime) < self.cache_ttl:
            return json.loads(cache_file.read_text())

        url = f"{BASE_URL}{path}"
        try:
            resp = self.session.get(
                url,
                params=params,
                timeout=30,
                proxies=_NO_PROXY,
            )
        except requests.RequestException as e:
            raise TMDBError(
                "Could not reach TMDB (network/proxy). "
                "Try running Streamlit in a normal terminal outside Cursor's proxy, "
                f"or check your connection. Details: {e.__class__.__name__}"
            ) from e
        if resp.status_code != 200:
            raise TMDBError(f"TMDB {resp.status_code}: {_redact(resp.text[:200])}")
        data = resp.json()
        cache_file.write_text(json.dumps(data))
        return data

    def genres(self) -> list[dict[str, Any]]:
        return self._get("/genre/movie/list").get("genres", [])

    def search_movies(self, query: str, page: int = 1) -> list[dict[str, Any]]:
        data = self._get("/search/movie", {"query": query, "page": page, "include_adult": False})
        return data.get("results", [])

    def movie(self, movie_id: int) -> dict[str, Any]:
        return self._get(
            f"/movie/{movie_id}",
            {"append_to_response": "credits,keywords,recommendations,similar"},
        )

    def popular(self, page: int = 1) -> list[dict[str, Any]]:
        return self._get("/movie/popular", {"page": page}).get("results", [])

    def top_rated(self, page: int = 1) -> list[dict[str, Any]]:
        return self._get("/movie/top_rated", {"page": page}).get("results", [])

    def discover(self, **filters: Any) -> list[dict[str, Any]]:
        params = {k: v for k, v in filters.items() if v is not None and v != ""}
        return self._get("/discover/movie", params).get("results", [])

    def trending(self, window: str = "week") -> list[dict[str, Any]]:
        return self._get(f"/trending/movie/{window}").get("results", [])

    def person_credits(self, person_id: int) -> dict[str, Any]:
        return self._get(f"/person/{person_id}/movie_credits")

    @staticmethod
    def poster_url(path: str | None, size: str = "w342") -> str | None:
        if not path:
            return None
        return f"{IMAGE_BASE}/{size}{path}"

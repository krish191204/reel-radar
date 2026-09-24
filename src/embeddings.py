"""Optional sentence embeddings for richer vibe / taste matching."""

from __future__ import annotations

import logging
import os
from functools import lru_cache
from typing import Sequence

import numpy as np

_MODEL_NAME = "sentence-transformers/all-MiniLM-L6-v2"
_backend: str | None = None
_log = logging.getLogger(__name__)

# Proxy env vars that sandboxed shells set and that break HF Hub + HTTPS_PROXY tunnels.
_PROXY_ENV_KEYS = (
    "HTTP_PROXY",
    "HTTPS_PROXY",
    "ALL_PROXY",
    "http_proxy",
    "https_proxy",
    "all_proxy",
)


def _scrub_proxy_env() -> dict[str, str]:
    """Return and remove every proxy env var so HF Hub / httpx talk direct."""
    saved: dict[str, str] = {}
    for key in _PROXY_ENV_KEYS:
        value = os.environ.pop(key, None)
        if value is not None:
            saved[key] = value
    return saved


def _restore_env(saved: dict[str, str]) -> None:
    for key, value in saved.items():
        os.environ[key] = value


def _mark_unavailable(reason: Exception | str) -> None:
    global _backend
    _backend = "none"
    _model.cache_clear()
    embedding_backend.cache_clear()
    _log.warning("MiniLM unavailable (%s); falling back to TF-IDF.", reason)


@lru_cache(maxsize=1)
def embedding_backend() -> str:
    """Return 'minilm' if sentence-transformers can load, else 'none'."""
    global _backend
    if _backend is not None:
        return _backend
    try:
        from sentence_transformers import SentenceTransformer  # noqa: F401

        # Probe load now so proxy/download failures don't crash Streamlit later.
        _model()
        _backend = "minilm"
    except Exception as e:
        _backend = "none"
        _log.warning("MiniLM unavailable (%s); falling back to TF-IDF.", e)
    return _backend


@lru_cache(maxsize=1)
def _model():
    from sentence_transformers import SentenceTransformer

    # Prefer the local HF cache — Cursor/proxy envs often 403 Hugging Face Hub.
    try:
        return SentenceTransformer(_MODEL_NAME, local_files_only=True)
    except Exception as local_err:
        _log.info("Local MiniLM miss (%s); trying Hub download…", local_err)
        saved = _scrub_proxy_env()
        try:
            return SentenceTransformer(_MODEL_NAME)
        except Exception as hub_err:
            raise RuntimeError(
                f"Could not load MiniLM from cache or Hub: {hub_err}"
            ) from hub_err
        finally:
            _restore_env(saved)


def encode_texts(texts: Sequence[str], *, batch_size: int = 64) -> np.ndarray | None:
    """
    Encode texts to L2-normalized dense vectors.
    Returns None if the embedding backend is unavailable.
    """
    if embedding_backend() == "none":
        return None
    cleaned = [t if t and t.strip() else "unknown film" for t in texts]
    try:
        model = _model()
        vectors = model.encode(
            cleaned,
            batch_size=batch_size,
            show_progress_bar=False,
            convert_to_numpy=True,
            normalize_embeddings=True,
        )
        return np.asarray(vectors, dtype=np.float32)
    except Exception as e:
        _mark_unavailable(e)
        return None


def encode_query(text: str) -> np.ndarray | None:
    mat = encode_texts([text])
    if mat is None:
        return None
    return mat[0]

"""Quality gates so obscure / fake-rated TMDB stubs don't pollute recommendations."""

from __future__ import annotations

from typing import Any

# Floor for "real movie people have actually rated"
MIN_VOTE_COUNT = 30
MIN_OVERVIEW_LEN = 25
MIN_POPULARITY = 0.3
TV_MOVIE_GENRE = 10770
# Ignore perfect 10.0 / 0.0 from tiny samples entirely via Bayesian rating
BAYES_M = 50.0
BAYES_C = 6.5  # global prior around TMDB mean


def vote_count(movie: dict[str, Any]) -> int:
    try:
        return int(movie.get("vote_count") or 0)
    except (TypeError, ValueError):
        return 0


def bayesian_rating(movie: dict[str, Any], m: float = BAYES_M, c: float = BAYES_C) -> float:
    """Shrink noisy averages toward a prior. 10.0 with 1 vote ≈ prior, not a masterpiece."""
    v = float(vote_count(movie))
    r = float(movie.get("vote_average") or 0.0)
    return (v / (v + m)) * r + (m / (v + m)) * c


def is_recommendable(
    movie: dict[str, Any],
    *,
    min_votes: int = MIN_VOTE_COUNT,
    min_overview: int = MIN_OVERVIEW_LEN,
    min_popularity: float = MIN_POPULARITY,
) -> bool:
    if not movie.get("id"):
        return False
    if movie.get("adult"):
        return False
    if movie.get("video"):
        return False
    if not (movie.get("title") or movie.get("original_title")):
        return False
    if vote_count(movie) < min_votes:
        return False
    overview = (movie.get("overview") or "").strip()
    if len(overview) < min_overview:
        return False
    try:
        pop = float(movie.get("popularity") or 0.0)
    except (TypeError, ValueError):
        pop = 0.0
    if pop < min_popularity:
        return False
    date = movie.get("release_date") or ""
    if not date:
        return False
    year = date[:4]
    if year.isdigit() and int(year) > 2026:
        return False
    # Prefer titled theatrical films with at least one genre when present
    gids = movie.get("genre_ids")
    if gids is None:
        genres = movie.get("genres") or []
        gids = [g.get("id") for g in genres if isinstance(g, dict)]
    if gids is not None and len(list(gids)) == 0:
        return False
    if gids and TV_MOVIE_GENRE in gids:
        return False
    return True


def filter_catalog(movies: list[dict[str, Any]], **kwargs: Any) -> list[dict[str, Any]]:
    return [m for m in movies if is_recommendable(m, **kwargs)]

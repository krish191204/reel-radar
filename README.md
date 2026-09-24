# Reel Radar

A film recommender with a fun spin: **get to press play with confidence**, not another generic “similar movies” list.

Built on the [TMDB](https://www.themoviedb.org/) API with a content-based ML layer (TF-IDF + genre/year/runtime features, clustering, and a credit graph).

## Pages

Multipage Streamlit site — start at Home, navigate from the left sidebar:

1. **Home** — welcome + taste summary
2. **Tonight Decoder** — time left + energy + hard-no genres → 3 picks
3. **Anti-Bubble** — comfort / stretch / risk
4. **Taste Twin** — map your taste onto another decade
5. **Vibe Match** — free-text vibe → semantic neighbors
6. **Cinematic DNA** — shared directors, DPs, composers, cast
7. **Group Peace Treaty** — minimize max regret across watchers
8. **Mood Map** — spoiler-free mood territories + in-cluster picks
9. **Behind the Scenes** — rating → model introspection

Taste booth (Letterboxd import + loves/avoids) lives in the **sidebar on every page**.

## Setup

```bash
cd reel-radar
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # then put your TMDB API key in .env
python scripts/ingest_catalog.py --target 3500
python scripts/clean_catalog.py
streamlit run app.py
```

### Taste import

Upload a Letterboxd `ratings.csv` (columns `Name,Year,Rating`) in the sidebar, or use the sample at `data/examples/letterboxd_sample.csv`. Ratings ≥ 3.5 become likes; ≤ 2.0 become dislikes.

### Feature backend

Uses MiniLM sentence embeddings + TF-IDF + metadata when `sentence-transformers` is installed (`minilm+tfidf+meta`). Falls back to TF-IDF + metadata otherwise.

### Ranking + evaluation

Tonight Decoder (and Anti-Bubble) use a **margin ranker**:

`score ≈ w_taste·sim(taste) − w_avoid·sim(avoid) + quality + energy/runtime/year fits − mild popularity penalty`

Each ticket shows a contribution breakdown. “Not interested” / “Watched” buttons write to `data/events.jsonl` and skips feed back into blocking + dislike taste.

Temporal holdout eval + weight tuning:

```bash
python scripts/eval_holdout.py --csv data/examples/letterboxd_sample.csv --tune --k 10
```

Writes `data/eval_report.json` and (with `--tune`) `data/ranker_weights.json`.

### Catalog coverage

`scripts/ingest_catalog.py` uses **stratified decade + genre quotas** before popularity fill so Mood Map / Taste Twin aren’t stuck on modern hits.

Never commit `.env`. If this key was pasted into chat, rotate it in the [TMDB settings](https://www.themoviedb.org/settings/api).

## Project layout

- `app.py` — Home page
- `pages/` — mode pages (Streamlit multipage)
- `src/streamlit_shell.py` — shared taste booth + workspace loader
- `src/tmdb.py` — API client + disk cache
- `src/features.py` — feature space + taste profiles
- `src/ranking.py` — margin score + tunable weights
- `src/eval.py` — holdout metrics / ablations
- `src/events.py` — impression / skip / watch log
- `src/catalog.py` — catalog builder
- `src/recommenders.py` — all recommendation modes
- `scripts/eval_holdout.py` — offline evaluation CLI

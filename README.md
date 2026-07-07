# Catalog Matcher — MVP (v1, no LLM)

Matches an internal item list (`Our_Items.xlsx`) against a government or
supplier catalog (`Government_Catalog.xlsx`), using deterministic
matching only. LLM-based reranking is deliberately deferred to v2 — the
architecture already has a slot for it (see "Architecture" below).

## Requirements

- **Python 3.11+**
- **Node.js 20+**
- **Docker** (optional, recommended for a one-command start)

## Run it

```bash
docker compose up --build
```

- Frontend: http://localhost:5173
- Backend API docs: http://localhost:8000/docs

You can also run without Docker — see "Local dev (without Docker)" below.

## Workflow

1. Upload `Government_Catalog.xlsx` (columns: Government Code, Product Name,
   Brand, Model, Description, Technical Specifications, Price — header
   names are matched loosely, so small variations are fine, including
   Russian headers).
2. Upload `Our_Items.xlsx` (columns: Item Code, Item Name, Description,
   Quantity).
3. Click "Run matching". For each internal item this:
   - retrieves the top 20 candidates by TF-IDF cosine similarity
   - applies deterministic filters (exact/fuzzy code match boosts,
     minimum-score cutoff)
   - ranks and keeps the top 3, each with a confidence score (0–100%)
     and a short explanation
4. Review the table. The best match is pre-selected; click any other
   candidate's radio button to pick it instead, or use "Manual override"
   to search the full catalog and pick something outside the top 3.
5. Click "Export" to download all results, "Export best matches" to
   download only high-confidence matches (default ≥80%), or "Export best
   matches in batches of 100" to download the best matches in batches of
   100 rows inside a single `.zip` archive.

## Architecture

```
backend/app/
  matching/
    base.py                # BaseRetriever / BaseFilter / BaseRanker interfaces
    tfidf_retriever.py      # v1: TF-IDF cosine similarity (no external calls)
    deterministic_filter.py # rule-based filtering (code match, score floor)
    heuristic_ranker.py     # v1: sort-by-score ranker
    factory.py              # <- the ONLY place that wires implementations together
  models/db_models.py       # CatalogSource, CatalogProduct, InternalItem, MatchResult
  services/
    excel_import.py         # tolerant Excel header parsing (pandas/openpyxl)
    normalize.py             # text/code/number cleaning
    export.py                 # export file generation (.xlsx / .zip)
  api/routes.py              # upload / run-matching / review / export endpoints
```

Two things make this extensible without touching the matching engine:

- **Multiple catalogs**: `CatalogSource` scopes every catalog product row.
  Adding a new supplier catalog is just another upload with a different
  `source_name` — no schema or engine changes.
- **Swappable pipeline stages**: routes.py only calls
  `app.matching.factory.build_engine(db, source_id)`. To add embeddings
  (pgvector) + an LLM reranker later:
  1. implement `EmbeddingRetriever(BaseRetriever)` querying pgvector
  2. implement `LLMRanker(BaseRanker)` calling the OpenAI API
  3. change `factory.py` to use them instead of the TF-IDF/heuristic
     versions — nothing else in the app needs to change.

`pgvector` is already provisioned in `docker-compose.yml` (the `db`
service uses the `pgvector/pgvector:pg16` image) so v2 doesn't need an
infra change either, just a new column + retriever implementation.

## First run on a new machine

```bash
# Option A — Docker (recommended)
docker compose up --build

# Option B — local
cd backend && python -m venv .venv && pip install -r requirements.txt
uvicorn app.main:app --reload
# in another terminal:
cd frontend && npm ci && npm run dev
```

## Local dev (without Docker)

Backend:
```bash
cd backend
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\Activate.ps1
pip install -r requirements.txt
uvicorn app.main:app --reload
```

By default a local SQLite file (`catalog_matcher.db`) is used — no
PostgreSQL install required. To use Postgres/pgvector, set the
`DATABASE_URL` environment variable and install `requirements-postgres.txt`.

Frontend:
```bash
cd frontend
npm install
npm run dev
```

## Known v1 limitations (by design)

- Matching is TF-IDF + rules, not semantic embeddings or an LLM — good
  enough for exact/near-exact naming, weaker on paraphrased descriptions.
  This is the intended v1 scope; v2 adds the LLM stage.
- No auth — add before exposing beyond localhost/internal network.
- Excel header matching is alias-based (see `CATALOG_HEADER_ALIASES` /
  `ITEM_HEADER_ALIASES` in `excel_import.py`); very unusual headers may
  need a new alias added.

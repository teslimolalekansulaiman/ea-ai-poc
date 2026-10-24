# Deploying the EA GraphRAG Wiki

Two ways to run it. **Local** is one process reading the filesystem; **Cloud Run** is the
split deployment for a shared/demo environment. The code is identical — the only
difference is a handful of environment variables.

---

## How it fits together

| Concern | Local dev | Cloud Run (split) |
|---|---|---|
| App (API + UI) | one `uvicorn` process | container on **Cloud Run** |
| Knowledge base (wiki pages, blocks, images, graph JSON) | `./data/` on disk | **GCS bucket** (`FILE_BACKEND=gcs`) |
| Chats + use-case runs (history) | SQLite `data/app.db` | **Cloud SQL Postgres** (`HISTORY_BACKEND=postgres`) |
| Graph + vectors | ArcadeDB in Docker | **ArcadeDB on a VM**, reached over the VPC |
| Model (LLM) | `claude` CLI or OpenRouter | **Pulse** (public, reachable from Cloud Run) |

**Why the split exists:** the VM that hosts ArcadeDB has no outbound internet, and the
model endpoint (Pulse) is public — so the app has to run where it *can* reach Pulse, which
is Cloud Run. Cloud Run is stateless (no durable disk, many short-lived instances), so the
KB and history move off local disk into GCS and Postgres.

**Two independent deploy tracks:**

1. **The image** carries *code + the built UI only* — never `data/`. At runtime it reads
   the KB from the bucket. (`.dockerignore` keeps `data/` out of the build context.)
2. **The data** is published to the bucket separately, by `scripts/publish.sh`. Nothing is
   auto-synced: your local `data/` goes to prod only if you point the publish script at it.

The app reads the bucket **live** (no caching), so a re-publish is visible immediately —
no image rebuild, no restart.

---

## Local development

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt           # full set (includes docling for ingestion)
cp .env.example .env                       # set ARCADEDB_PASSWORD + EAWIKI_ARCADE_PASSWORD (same value)
docker-compose up -d                       # ArcadeDB (+ Phoenix)

# Build the knowledge base (the pipeline):
PYTHONPATH=src python -m eawiki.parse
PYTHONPATH=src python -m eawiki.tables    --backend openrouter
PYTHONPATH=src python -m eawiki.subjects  --backend openrouter
PYTHONPATH=src python -m eawiki.pages     --backend openrouter --workers 8
PYTHONPATH=src python -m eawiki.reconcile
PYTHONPATH=src python -m eawiki.describe  --backend openrouter
PYTHONPATH=src python -m eawiki.embed     --backend st        # see "Embeddings" below
PYTHONPATH=src python -m eawiki.load

cd ui && npm ci && npm run build && cd ..  # build the UI into ui/dist
PYTHONPATH=src uvicorn eawiki.api.app:app --host 127.0.0.1 --port 8099
```

`FILE_BACKEND` and `HISTORY_BACKEND` default to `local`/`sqlite`, so nothing else is needed
for local dev.

---

## Cloud Run deployment

### Prerequisites (one-time GCP setup)

- **GCS bucket** for the KB — create with public-access-prevention and uniform
  bucket-level access. Grant the Cloud Run service account **Storage Object Admin** on it
  (Object Viewer is enough if you never write from the app — we run read-only).
- **Cloud SQL Postgres** instance + a database. Grant the service account **Cloud SQL
  Client**.
- **VPC connector** so Cloud Run can reach ArcadeDB on the VM's internal IP.
- **ArcadeDB** already running on the VM (port 2480).

### 1. Build the KB offline, with the embedding you'll serve with

Run the pipeline anywhere with model access (your laptop is fine). Build into a separate
folder if you want to keep local sample data out of prod:

```bash
EAWIKI_DATA=data-prod PYTHONPATH=src python -m eawiki.parse     # ... through ...
EAWIKI_DATA=data-prod PYTHONPATH=src python -m eawiki.embed --backend <st|openai|...>
```

> **⚠️ The embedding must match on both ends.** The query side reads the embedder back
> from `graph/embeddings_meta.json` (not from any env var), so whatever you build the index
> with, Cloud Run must be able to run the same thing. A mismatch returns wrong results
> **silently**. Decide this *before* you build.

### 2. Publish the KB (bucket + ArcadeDB) — **do this before deploying the app**

```bash
GCS_BUCKET=ea-wiki-kb-myproj \
EAWIKI_ARCADE_URL=http://<vm-internal-ip>:2480 \
EAWIKI_ARCADE_PASSWORD=<vm-arcadedb-password> \
./scripts/publish.sh data-prod
```

It `rsync`s the data into the bucket (an exact mirror, excluding `app.db` and ingest caches)
and loads the graph + vectors into ArcadeDB. Flags: pass a `DATA_DIR` argument (default
`./data`); add `--skip-load` to update the bucket only.

### 3. Build + deploy the image

```bash
gcloud run deploy ea-wiki \
  --source . \
  --region <REGION> \
  --vpc-connector <CONNECTOR> \
  --set-env-vars "FILE_BACKEND=gcs,GCS_BUCKET=ea-wiki-kb-myproj,\
HISTORY_BACKEND=postgres,EAWIKI_SERVE_ONLY=1,\
EAWIKI_API_BACKEND=pulse,VLM_PROXY_URL=https://<pulse-host>/v1/chat/completions,\
VLM_MODEL=<pulse-chat-model>,EAWIKI_ARCADE_URL=http://<vm-internal-ip>:2480,\
EAWIKI_TRACING=off" \
  --set-secrets "DATABASE_URL=<secret>,VLM_PROXY_KEY=<secret>,EAWIKI_ARCADE_PASSWORD=<secret>"
```

`gcloud run deploy --source .` builds from the `Dockerfile` with Cloud Build. GCS auth is
automatic via the service account — there is no key to configure, only the bucket name
plus the IAM grant above.

### Re-publishing later

Just rerun `scripts/publish.sh` — the running app serves the new bucket contents
immediately (the graph is read fresh per request; pages/blocks/images always were). No
redeploy needed unless you changed the **embedding model** (that requires a matching image
— see Embeddings).

---

## Environment variables

| Variable | Values / example | Notes |
|---|---|---|
| `FILE_BACKEND` | `local` (default) · `gcs` | `gcs` reads the KB from the bucket |
| `GCS_BUCKET` | `ea-wiki-kb-myproj` | required when `FILE_BACKEND=gcs` |
| `GCS_PREFIX` | *(empty)* | optional sub-path within the bucket |
| `HISTORY_BACKEND` | `sqlite` (default) · `postgres` | chats + runs |
| `DATABASE_URL` | `postgresql://…` | required when `HISTORY_BACKEND=postgres` |
| `EAWIKI_SERVE_ONLY` | `1` on Cloud Run | read-only: disables add/remove/re-ingest/metamodel/use-case writes |
| `EAWIKI_API_BACKEND` | `cli` · `openrouter` · `pulse` | the LLM backend |
| `VLM_PROXY_URL` | `https://…/v1/chat/completions` | OpenAI-compatible chat endpoint |
| `VLM_PROXY_KEY` / `VLM_API_KEY` | secret | model API key |
| `VLM_MODEL` | model id | chat model |
| `EAWIKI_EMBED_BACKEND` | `st` · `openai` · `vertex` · `hash` | **must match the index** — see below |
| `EMBED_MODEL` | `openai/text-embedding-3-small` | only for the `openai` embed backend |
| `EMBED_PROXY_URL` | `https://…/v1/embeddings` | defaults from `VLM_PROXY_URL` |
| `EAWIKI_ARCADE_URL` | `http://<vm-ip>:2480` | the app **connects** here |
| `EAWIKI_ARCADE_PASSWORD` | secret | the app connects with **this** |
| `ARCADEDB_PASSWORD` | secret | docker-compose var that **sets** the container password (local) |
| `EAWIKI_TRACING` | `off` in prod | Phoenix tracing; off = no-op |

See `.env.example` for a copy-paste starting point with LOCAL and CLOUD RUN profiles. A
`.env` file needs **one `KEY=value` per line**.

---

## Embeddings (the thing most likely to bite)

The index embedder and the serving embedder **must be identical**, because the serving side
reads the backend/model/dim from `graph/embeddings_meta.json` and a mismatch fails silently.

- **`EAWIKI_EMBED_BACKEND=openai`** (Pulse/OpenRouter): slim image, query embedding is one
  HTTPS call. The endpoint must serve the exact model the index was built with. Nothing extra
  to install.
- **`EAWIKI_EMBED_BACKEND=st`** (local `sentence-transformers`): self-contained, no API call
  for embeddings — but the model + torch must be in the image. **Uncomment
  `sentence-transformers` in `requirements-serve.txt`** (this makes the image much larger).

Changing the embedding model is the one case where re-publishing the data is not enough —
you must also rebuild/redeploy the image so it can run the new embedder.

---

## Files

| File | Role |
|---|---|
| `Dockerfile` | Cloud Run image (code + built UI, no data) |
| `requirements-serve.txt` | slim serving deps (no docling/torch/anthropic/phoenix) |
| `.dockerignore` | keeps `data/`, `docs/`, secrets out of the image |
| `scripts/publish.sh` | publish `data/` → GCS bucket + load ArcadeDB |
| `.env.example` | env templates (local + Cloud Run) |
| `requirements.txt` | full deps for ingestion + local dev |

# Cloud Run serving image for the EA GraphRAG wiki.
#
# Carries ONLY code + the built React UI. It does NOT contain the knowledge base: with
# FILE_BACKEND=gcs the app reads pages/blocks/images/graph from the GCS bucket at runtime,
# and history from Postgres. Ingestion runs offline (see scripts/publish.sh). Keeping data
# out keeps the image small and means a bucket upload is live without rebuilding the image.

# ---- Stage 1: build the React UI (served by FastAPI from ui/dist) ----
FROM node:20-bookworm-slim AS ui
WORKDIR /ui
COPY ui/package.json ui/package-lock.json ./
RUN npm ci
COPY ui/ ./
RUN npm run build          # -> /ui/dist

# ---- Stage 2: Python serving image ----
FROM python:3.12-slim AS serve
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONPATH=/app/src \
    EAWIKI_TRACING=off \
    PORT=8080
WORKDIR /app

# Dependencies first, so edits to source don't bust the pip layer cache.
COPY requirements-serve.txt ./
RUN pip install --no-cache-dir -r requirements-serve.txt

# App code + the built UI. No data/ (read from GCS), no docs/ (ingest sources).
COPY src/ ./src/
COPY --from=ui /ui/dist ./ui/dist

EXPOSE 8080
# Cloud Run routes traffic to $PORT; honor it. WEB resolves to ./ui/dist from this CWD.
CMD ["sh", "-c", "exec uvicorn eawiki.api.app:app --host 0.0.0.0 --port ${PORT}"]

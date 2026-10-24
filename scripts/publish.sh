#!/usr/bin/env bash
# Publish an offline-built knowledge base to the Cloud Run split:
#   1) sync data/ -> the GCS bucket   (what Cloud Run serves — read live, no cache)
#   2) load graph + vectors -> ArcadeDB on the VM   (what Ask retrieves over)
#
# Build the KB first (the pipeline: parse -> ... -> embed), with the SAME embedding you
# serve with — the query side reads the embedder back from embeddings_meta.json, so a
# mismatch silently breaks retrieval. Then run this from a host that can reach BOTH the
# bucket and the VM's ArcadeDB.
#
# Your local ./data never leaves the machine unless you point DATA_DIR at it: pass a
# prod-only build (e.g. ./data-prod) to keep sample data out of prod.
#
# Usage:
#   GCS_BUCKET=ea-wiki-kb-myproj \
#   EAWIKI_ARCADE_URL=http://10.0.0.5:2480 EAWIKI_ARCADE_PASSWORD=secret \
#   ./scripts/publish.sh [DATA_DIR]            # DATA_DIR defaults to ./data
#
#   # bucket only (skip the ArcadeDB load):
#   GCS_BUCKET=... ./scripts/publish.sh data-prod --skip-load

set -euo pipefail

DATA_DIR="${1:-data}"
SKIP_LOAD=""
[ "${2:-}" = "--skip-load" ] && SKIP_LOAD=1

: "${GCS_BUCKET:?set GCS_BUCKET (bucket name, no gs:// prefix)}"
PREFIX="${GCS_PREFIX:+/${GCS_PREFIX#/}}"          # optional sub-path within the bucket
DEST="gs://${GCS_BUCKET}${PREFIX}"

[ -d "$DATA_DIR" ] || { echo "no such data dir: $DATA_DIR" >&2; exit 1; }
[ -f "$DATA_DIR/graph/embeddings_meta.json" ] || \
  echo "warn: $DATA_DIR/graph/embeddings_meta.json missing — did you run the embed step?" >&2

echo "==> 1/2  sync  $DATA_DIR  ->  $DEST"
# -d makes the bucket an exact mirror (removed docs' pages/images disappear). Exclude the
# SQLite history (now Postgres) and the ingest-only caches — the serving app reads none of
# them. -x takes ONE regex, matched against each path relative to $DATA_DIR.
gsutil -m rsync -r -d \
  -x '(^|.*/)app\.db$|(^|.*/)[^/]*_cache/.*|(^|.*/)\.reingest_needed$' \
  "$DATA_DIR" "$DEST"

if [ -n "$SKIP_LOAD" ]; then
  echo "==> 2/2  skipped (--skip-load). Bucket is live immediately; ArcadeDB unchanged."
  exit 0
fi

echo "==> 2/2  load graph + vectors into ArcadeDB  ($EAWIKI_ARCADE_URL)"
: "${EAWIKI_ARCADE_URL:?set EAWIKI_ARCADE_URL (the VM ArcadeDB, reachable from here)}"
: "${EAWIKI_ARCADE_PASSWORD:?set EAWIKI_ARCADE_PASSWORD}"
PYTHONPATH="${PYTHONPATH:-src}" python -m eawiki.load \
  --graph       "$DATA_DIR/graph/graph.json" \
  --embeddings  "$DATA_DIR/graph/embeddings.jsonl" \
  --meta        "$DATA_DIR/graph/embeddings_meta.json"

echo "==> done. Cloud Run serves the new bucket contents immediately (no restart; graph is read fresh)."

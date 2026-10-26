#!/usr/bin/env bash
# Build the knowledge base in Cloud Shell and publish it (bucket + ArcadeDB on the VM).
#
# Why here: the ingest stages need docling (heavy), Pulse, and — for the final load — the
# VM's ArcadeDB, which is reachable from Cloud Shell only through an IAP tunnel.
#
#   cd ~/ea-ai-poc && git pull origin claude/ea-deploy
#   tmux new -s ingest            # survives a dropped Cloud Shell connection
#   ./deploy/ingest.sh
#
# Adding a document for a demo: put the .docx in INPUT_DIR (default docs/samples; use a folder
# outside the repo for real documents, e.g. INPUT_DIR=$HOME/ea-inputs) and run this again.
# The pipeline is a full rebuild; per-step caches under data/graph/ make unchanged work cheap.
#
# Secrets are read from Secret Manager into this process only; nothing is printed or written.
set -euo pipefail

PROJECT="${PROJECT:-$(gcloud config get-value project 2>/dev/null)}"
GCS_BUCKET="${GCS_BUCKET:-$PROJECT-ea-kb}"
INPUT_DIR="${INPUT_DIR:-docs/samples}"
VENV="${VENV:-/tmp/ea-venv}"      # outside $HOME: Cloud Shell's home is small, /tmp is not
WORKERS="${WORKERS:-4}"

export HF_HOME="${HF_HOME:-/tmp/hf}" PYTHONPATH=src
export VLM_PROXY_URL="${VLM_PROXY_URL:-https://pulse.deloitte.com/chat/completions}"
export VLM_MODEL="${VLM_MODEL:-claude-sonnet-5-5}"
export EMBED_MODEL="${EMBED_MODEL:-gemini-embedding-2}"
export EAWIKI_TRACING=off

[ -d "$INPUT_DIR" ] || { echo "no such input dir: $INPUT_DIR" >&2; exit 1; }

if [ ! -x "$VENV/bin/python" ]; then
  echo "==> creating venv at $VENV (CPU torch first, to avoid the CUDA download)"
  python3 -m venv "$VENV"
  "$VENV/bin/pip" install -q torch torchvision --index-url https://download.pytorch.org/whl/cpu
  "$VENV/bin/pip" install -q docling==2.139.0 numpy certifi
fi
export PATH="$VENV/bin:$PATH"

VLM_PROXY_KEY="$(gcloud secrets versions access latest --secret=pulse-key)"
EAWIKI_ARCADE_PASSWORD="$(gcloud secrets versions access latest --secret=arcadedb-root-password)"
export VLM_PROXY_KEY EAWIKI_ARCADE_PASSWORD

# FROM_STEP lets you resume (e.g. FROM_STEP=embed) after a failure without re-running the
# earlier stages. EMBED_BATCH=1 sends one text per request: some embedding routes fold a
# multi-text batch into fewer vectors.
FROM_STEP="${FROM_STEP:-parse}"
EMBED_BATCH="${EMBED_BATCH:-1}"

# A full run starts from a clean slate for per-document outputs so a removed document
# leaves nothing behind (what the app's own re-ingest does). Step caches are kept.
[ "$FROM_STEP" = parse ] && rm -f data/blocks/*.blocks.json data/pages/*.md

started=""
[ "$FROM_STEP" = publish ] && started=skip   # FROM_STEP=publish: skip the build, just publish
for step in parse tables subjects pages reconcile describe embed index community summaries; do
  [ "$started" = skip ] && break
  [ "$step" = "$FROM_STEP" ] && started=1
  [ -n "$started" ] || continue
  echo; echo "==> $step"
  case "$step" in
    parse)     python -m eawiki.parse --in "$INPUT_DIR" ;;
    pages)     python -m eawiki.pages --backend pulse --workers "$WORKERS" ;;
    reconcile) python -m eawiki.reconcile --adjudicate pulse --semantic \
                 --merge-mode "${EAWIKI_MERGE_MODE:-report}" ;;
    embed)     python -m eawiki.embed --backend openai --batch-size "$EMBED_BATCH" ;;
    index)     python -m eawiki.entity_index ;;
    # Steps 7-9. Files only here: the graph is loaded into ArcadeDB by publish.sh below,
    # after which the Community vertices would have to be projected (run the app's
    # re-ingest, or `python -m eawiki.community`, to do that).
    community) python -m eawiki.community --no-load ;;
    summaries) python -m eawiki.summaries --backend pulse --min-size 3 --no-load ;;
    # landscape pages are not built (see src/eawiki/pipeline.py); add the step back here and
    # to the loop above to produce them.
    *)         python -m "eawiki.$step" --backend pulse ;;
  esac
done
[ -n "$started" ] || { echo "unknown FROM_STEP: $FROM_STEP" >&2; exit 1; }

echo; echo "==> opening IAP tunnel to ArcadeDB"
gcloud compute start-iap-tunnel ea-dev-vm 2480 --local-host-port=localhost:2480 \
  --zone=me-central2-a >/tmp/ea-tunnel.log 2>&1 &
TUNNEL=$!
trap 'kill $TUNNEL 2>/dev/null || true' EXIT
for _ in $(seq 1 30); do
  curl -sf http://localhost:2480/api/v1/ready >/dev/null && break
  sleep 2
done
curl -sf http://localhost:2480/api/v1/ready >/dev/null || { echo "tunnel not ready; see /tmp/ea-tunnel.log" >&2; exit 1; }

GCS_BUCKET="$GCS_BUCKET" EAWIKI_ARCADE_URL=http://localhost:2480 ./scripts/publish.sh data

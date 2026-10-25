#!/usr/bin/env bash
# Run authenticated local proxies to both Cloud Run services from one Cloud Shell tab.
#   8080 -> ea-wiki         (read-only viewer)
#   8081 -> ea-wiki-author  (uploads and ingest)
# Open them with Web Preview ("Change port"). The proxy's login token lasts about an hour,
# so the pair is restarted every 45 minutes. Ctrl+C stops both.
#
# Cloud Shell itself ends after a period of inactivity, so this is a working tool for a
# session, not a permanent address. A browser-reload URL needs IAP in front of the services.
set -u
REGION="${REGION:-me-central2}"

stop() { pkill -f "run services proxy" 2>/dev/null; }
trap 'stop; exit 0' INT TERM
stop
while true; do
  gcloud run services proxy ea-wiki --region "$REGION" --port 8080 &
  gcloud run services proxy ea-wiki-author --region "$REGION" --port 8081 &
  sleep 2700
  stop
  wait 2>/dev/null
done

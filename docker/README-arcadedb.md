# ArcadeDB — local & GCP dev VM

ArcadeDB is the **store** the pipeline loads into at **Step 6** (graph today; vectors
too if we keep them in-DB). Files under `data/` stay the system of record — the DB is a
rebuildable projection, so it's always safe to drop and reload.

The `docker-compose.yml` at the repo root runs the **official image** (`arcadedata/arcadedb`);
there is nothing to build. The same file runs locally and on the GCP VM.

## Local (this machine)

```bash
cp .env.example .env          # then edit .env and set a real password
docker compose up -d          # or: docker-compose up -d   (Compose v1)
```

`docker compose` not found? Docker is installed here but the Compose v2 plugin may not be.
Check with `docker compose version`. If missing, either install the plugin
(`docker-compose-plugin`) or use the standalone `docker-compose` binary — the file works with
both.

### Verify it's up
```bash
curl -s http://localhost:2480/api/v1/ready && echo " <- ready"
# list databases (should include "eawiki"):
curl -s -u root:"$ARCADEDB_PASSWORD" http://localhost:2480/api/v1/databases
```
Then open **http://localhost:2480** for Studio (user `root`, your password).

### Create the DB manually (if auto-create didn't)
```bash
curl -X POST http://localhost:2480/api/v1/server \
  -u root:"$ARCADEDB_PASSWORD" \
  -H 'Content-Type: application/json' \
  -d '{"command":"create database eawiki"}'
```

### Stop / reset
```bash
docker compose down            # stop, keep data (named volumes persist)
docker compose down -v         # stop AND delete all data (fresh start)
```

## GCP dev VM (replicate later)

Same `docker-compose.yml`. On the VM:

1. **Install Docker + Compose plugin**, then copy this repo (or just `docker-compose.yml` +
   `.env`) to the VM.
2. **Pin the image tag** in `docker-compose.yml` (replace `:latest` with a specific version
   from https://hub.docker.com/r/arcadedata/arcadedb/tags) so dev matches a known build.
3. **Set a strong `ARCADEDB_PASSWORD`** in `.env` (not the local placeholder).
4. **Do NOT expose 2480/2424 to the public internet.** Keep the GCP firewall closed to those
   ports and reach the DB over the VM's private network / SSH tunnel / IAP (see the deployment
   runbook). The app talks to it on `localhost` from the same VM, or over the VPC.
5. `docker compose up -d`. Data lives in Docker named volumes on the VM disk; snapshot the disk
   or use `backups` volume + ArcadeDB backup for durability.

## Ports
- **2480** — HTTP: Studio UI + REST API (what the Python loader will use)
- **2424** — binary protocol (native drivers)

## Where vectors go (decide at Step 5/6)
ArcadeDB has a vector (HNSW) index, so embeddings *can* live in-DB alongside the graph (one
store, one query surface). Alternatively keep a lightweight local vector index and load later.
Computing embeddings (Step 5) needs no DB either way; this only affects Step 6.

#!/usr/bin/env bash
#
# One-shot deploy of the rebuilt /learn database to Coolify (Hetzner).
# Data-only: swaps /data/gadaoromo.db inside the app container. No app code changes.
#
# Usage (from the repo dir, in Git Bash):
#   ./deploy_learn_fix.sh <container_name>
#   # or:  CONTAINER=myapp ./deploy_learn_fix.sh
#   # host/db default to the known values below; override with env vars if needed.
#
# Safety: verifies checksum before and after transfer, stops the app during the
# file swap, backs up the existing DB, removes stale WAL/SHM, restarts, verifies
# the eligible-phrase count, and aborts on any error.

set -euo pipefail

HOST="${HOST:-root@167.233.137.118}"
CONTAINER="${CONTAINER:-${1:-}}"
LOCAL_DB="$(cd "$(dirname "$0")" && pwd)/gadaoromo_deploy.db"

[ -f "$LOCAL_DB" ] || { echo "ERROR: $LOCAL_DB not found. Run r2_backfill.py first."; exit 1; }
if [ -z "$CONTAINER" ]; then
  echo "ERROR: container name required."
  echo "  Find it with:  ssh $HOST docker ps"
  echo "  Then run:      ./deploy_learn_fix.sh <container_name>"
  exit 1
fi

SHA=$(sha256sum "$LOCAL_DB" | awk '{print $1}')

# eligible-phrase count expected after deploy (derived from the DB we're shipping)
EXPECTED_ELIG=$(DB_PATH="$LOCAL_DB" python - <<'PY'
import sqlite3, os
c = sqlite3.connect(os.environ['DB_PATH'])
print(c.execute('''select count(*) from (select phrase_id from (
  select entry_id phrase_id, lower(replace(trim(lang_code),'_','-')) lk
    from generated_tts_audio where entry_type='phrase' and file_path like 'https://%' and trim(lang_code)!=''
  union
  select phrase_id, lower(replace(trim(lang_code),'_','-')) lk
    from generated_phrase_translations where tts_audio_url like 'https://%' and trim(lang_code)!=''
) group by phrase_id having count(distinct lk)>=2)''').fetchone()[0])
PY
)

echo "[local]  $LOCAL_DB"
echo "[local]  sha256=$SHA"
echo "[local]  expected eligible phrases=$EXPECTED_ELIG"
echo "[local]  uploading to $HOST:/tmp/gadaoromo.db ..."
scp "$LOCAL_DB" "$HOST:/tmp/gadaoromo.db"

echo "[local]  running remote swap on container '$CONTAINER' ..."
ssh "$HOST" EXPECTED_SHA="$SHA" EXPECTED_ELIG="$EXPECTED_ELIG" CONTAINER="$CONTAINER" 'bash -s' <<'REMOTE'
set -euo pipefail

echo "[server] verifying transfer checksum..."
ACTUAL=$(sha256sum /tmp/gadaoromo.db | awk '{print $1}')
if [ "$ACTUAL" != "$EXPECTED_SHA" ]; then
  echo "[server] CHECKSUM MISMATCH: got $ACTUAL expected $EXPECTED_SHA"; exit 1
fi
echo "[server] checksum ok"

docker inspect "$CONTAINER" >/dev/null 2>&1 || { echo "[server] no such container: $CONTAINER"; docker ps; exit 1; }

DB_PATH=$(docker exec "$CONTAINER" printenv DB_PATH 2>/dev/null || true)
DB_PATH=${DB_PATH:-/data/gadaoromo.db}
DB_DIR=$(dirname "$DB_PATH")
DB_BASE=$(basename "$DB_PATH")
echo "[server] target DB path in container: $DB_PATH"

# Resolve the host-side path for the volume mounted at $DB_DIR (if any),
# so we can manipulate WAL/SHM while the container is stopped.
HOST_DIR=$(docker inspect "$CONTAINER" \
  --format "{{range .Mounts}}{{if eq .Destination \"$DB_DIR\"}}{{.Source}}{{end}}{{end}}" 2>/dev/null || true)

# verifier script (checks eligible phrase count the /learn loader requires)
cat > /tmp/verify_learn.py <<'PY'
import sqlite3, os
c = sqlite3.connect(os.environ.get('DB_PATH', '/data/gadaoromo.db'))
n = c.execute('''select count(*) from (select phrase_id from (
  select entry_id phrase_id, lower(replace(trim(lang_code),'_','-')) lk
    from generated_tts_audio where entry_type='phrase' and file_path like 'https://%' and trim(lang_code)!=''
  union
  select phrase_id, lower(replace(trim(lang_code),'_','-')) lk
    from generated_phrase_translations where tts_audio_url like 'https://%' and trim(lang_code)!=''
) group by phrase_id having count(distinct lk)>=2)''').fetchone()[0]
print('eligible phrases:', n)
PY

STAMP=$(date +%Y%m%d_%H%M%S)
echo "[server] stopping container..."
docker stop "$CONTAINER" >/dev/null

echo "[server] backing up current DB -> /tmp/gadaoromo_backup_$STAMP.db"
docker cp "$CONTAINER:$DB_PATH" "/tmp/gadaoromo_backup_$STAMP.db" 2>/dev/null \
  || echo "[server]   (no existing DB to back up)"

if [ -n "$HOST_DIR" ] && [ -d "$HOST_DIR" ]; then
  echo "[server] swapping via host volume path: $HOST_DIR"
  cp /tmp/gadaoromo.db "$HOST_DIR/$DB_BASE"
  rm -f "$HOST_DIR/$DB_BASE-wal" "$HOST_DIR/$DB_BASE-shm"
else
  echo "[server] host volume path not found; swapping via docker cp"
  docker cp /tmp/gadaoromo.db "$CONTAINER:$DB_PATH"
fi

echo "[server] starting container..."
docker start "$CONTAINER" >/dev/null

# if we couldn't reach the host path, clear stale WAL/SHM now that it's running
if [ -z "$HOST_DIR" ] || [ ! -d "$HOST_DIR" ]; then
  docker exec "$CONTAINER" sh -c "rm -f '$DB_PATH-wal' '$DB_PATH-shm'" 2>/dev/null || true
fi

echo "[server] verifying eligible phrase count in container..."
docker cp /tmp/verify_learn.py "$CONTAINER:/tmp/verify_learn.py"
ACT_ELIG=$(docker exec -e DB_PATH="$DB_PATH" "$CONTAINER" python3 /tmp/verify_learn.py | grep -oE '[0-9]+' | head -1)
echo "[server] eligible phrases in deployed DB: ${ACT_ELIG:-?} (expected $EXPECTED_ELIG)"
if [ "${ACT_ELIG:-x}" != "$EXPECTED_ELIG" ]; then
  echo "[server] WARNING: eligible count differs from expected — check DB_PATH / mount before trusting the page."
else
  echo "[server] OK — deployed DB matches expected."
fi
REMOTE

echo
echo "[local]  Deploy complete."
echo "[local]  Now open https://gadaadictionary.com/learn in incognito (?v=2 to bypass cache)."

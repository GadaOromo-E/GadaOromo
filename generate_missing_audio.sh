#!/usr/bin/env bash
#
# Generate the missing phrase audio via Azure TTS and upload to R2, then rebuild
# the deploy DB. Runs LOCALLY against gadaoromo.db (R2 is the shared audio store,
# so audio generated here is immediately usable in production).
#
# The text for all phrases already exists; this only synthesizes the missing
# audio (en/am/ar/fr/zh-CN, +om if AZURE_VOICE_OM is set) and skips anything
# already cached in R2.
#
# Usage:
#   ./generate_missing_audio.sh 20     # validation run: first 20 phrases
#   ./generate_missing_audio.sh        # full run (all ~2,966 remaining phrases)
#
# After a full run, deploy with:  ./deploy_learn_fix.sh <container_name>

set -euo pipefail
cd "$(cd "$(dirname "$0")" && pwd)"

LIMIT="${1:-0}"   # 0 = all

# The app auto-loads .env only when python-dotenv is installed (it calls
# load_dotenv at import). Ensure it's present so R2 + Azure creds are seen.
if ! python -c "import dotenv" 2>/dev/null; then
  echo "[gen] installing python-dotenv (needed so the app reads .env for R2/Azure)..."
  pip install python-dotenv
fi

echo "[gen] eligible phrases BEFORE:"
DB_PATH="C:\\data\\gadaoromo.db" python - <<'PY'
import sqlite3, os
c=sqlite3.connect(os.environ['DB_PATH'])
print("  ", c.execute('''select count(*) from (select phrase_id from (
  select entry_id phrase_id, lower(replace(trim(lang_code),'_','-')) lk from generated_tts_audio where entry_type='phrase' and file_path like 'https://%' and trim(lang_code)!=''
  union select phrase_id, lower(replace(trim(lang_code),'_','-')) lk from generated_phrase_translations where tts_audio_url like 'https://%' and trim(lang_code)!=''
) group by phrase_id having count(distinct lk)>=2)''').fetchone()[0])
PY

echo "[gen] running Azure TTS backfill for phrases (limit=$LIMIT; 0=all)..."
export FLASK_APP=app
python -m flask backfill-tts --entry-type phrase --limit "$LIMIT"

echo "[gen] normalizing any remaining local refs to R2 URLs + rebuilding gadaoromo_deploy.db ..."
python r2_backfill.py

echo
echo "[gen] Done. Review the 'eligible phrases AFTER' line above."
echo "[gen] If this was a validation run, spot-check audio on cdn.gadaadictionary.com,"
echo "[gen] then run the full pass:  ./generate_missing_audio.sh"
echo "[gen] When satisfied, deploy:  ./deploy_learn_fix.sh <container_name>"

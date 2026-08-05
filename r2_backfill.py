"""
Data-only recovery: rewrite local /uploads audio refs to their https R2 URLs.
Does NOT modify app code. Operates on a COPY of the source DB.

PHRASE audio (what /learn needs): hybrid match.
  1) exact basename in R2  -> use it (text hash matches, guaranteed consistent)
  2) else any R2 object for same phrase_id + language -> use it (restores what
     Railway served; audio wording may differ slightly from displayed text)
WORD audio + oromo `audio` table: exact match only (no wording drift on
dictionary pages, which are out of scope).

R2 key == os.path.basename(local_ref)         (app.py:5447)
public URL == R2_PUBLIC_BASE_URL + '/' + key  (app.py:2870)
"""
import os, re, shutil, sqlite3, boto3
from botocore.config import Config

# Source of truth is the DB the app actually uses (DB_PATH -> /data/gadaoromo.db,
# which resolves to C:\data\gadaoromo.db locally). This is where `flask
# backfill-tts` writes generated audio. Override with SRC_DB env var if needed.
SRC_DB = os.environ.get("SRC_DB", r"C:\data\gadaoromo.db")
OUT_DB = "gadaoromo_deploy.db"

env = {}
for line in open('.env', encoding='utf-8'):
    line = line.strip()
    if line and not line.startswith('#') and '=' in line:
        k, v = line.split('=', 1)
        env[k.strip()] = v.strip().strip('"').strip("'")

base = env['R2_PUBLIC_BASE_URL'].rstrip('/')
bucket = env['R2_BUCKET_NAME']
s3 = boto3.client('s3', endpoint_url=env['R2_ENDPOINT'].rstrip('/'),
                  aws_access_key_id=env['R2_ACCESS_KEY_ID'],
                  aws_secret_access_key=env['R2_SECRET_ACCESS_KEY'],
                  config=Config(signature_version='s3v4'), region_name='auto')


def bn(p):
    return os.path.basename((p or "").replace('\\', '/').strip())


def canon(l):
    l = (l or "").lower().replace('_', '-')
    for pre, out in (('en', 'en'), ('am', 'am'), ('ar', 'ar'), ('fr', 'fr'),
                     ('zh', 'zh-cn'), ('om', 'om'), ('or', 'om')):
        if l.startswith(pre):
            return out
    return l


PHRASE_RE = re.compile(r'^tts_phrase_(\d+)_([A-Za-z-]+)_')

print("Listing R2 bucket keys ...", flush=True)
keys = set()
phrase_idx = {}          # (phrase_id, canon_lang) -> sorted list of keys
tok = None
while True:
    kw = dict(Bucket=bucket, MaxKeys=1000)
    if tok:
        kw['ContinuationToken'] = tok
    r = s3.list_objects_v2(**kw)
    for o in r.get('Contents', []):
        k = o['Key']
        keys.add(k)
        m = PHRASE_RE.match(k)
        if m:
            phrase_idx.setdefault((int(m.group(1)), canon(m.group(2))), []).append(k)
    if r.get('IsTruncated'):
        tok = r.get('NextContinuationToken')
    else:
        break
for v in phrase_idx.values():
    v.sort()
print("R2 objects total:", len(keys), "| phrase+lang groups:", len(phrase_idx))

ELIG = """
select count(*) from (select phrase_id from (
  select entry_id phrase_id, lower(replace(trim(lang_code),'_','-')) lk
    from generated_tts_audio where entry_type='phrase' and file_path like 'https://%' and trim(lang_code)!=''
  union
  select phrase_id, lower(replace(trim(lang_code),'_','-')) lk
    from generated_phrase_translations where tts_audio_url like 'https://%' and trim(lang_code)!=''
) group by phrase_id having count(distinct lk)>=2)
"""

# checkpoint the source WAL into its main file so the copy captures recent writes
_src = sqlite3.connect(SRC_DB)
_src.execute("PRAGMA wal_checkpoint(TRUNCATE);")
_src.close()
shutil.copy2(SRC_DB, OUT_DB)
c = sqlite3.connect(OUT_DB)
print("eligible phrases BEFORE:", c.execute(ELIG).fetchone()[0])


def promote(label, select_sql, table, refcol, hybrid):
    rows = c.execute(select_sql).fetchall()   # -> (rowid, entry_id, lang_code, ref)
    exact = fallback = left = 0
    ups = []
    for rid, eid, lang, ref in rows:
        key = bn(ref)
        if key and key in keys:
            ups.append((base + '/' + key, rid)); exact += 1
            continue
        if hybrid and eid is not None:
            cand = phrase_idx.get((int(eid or 0), canon(lang)))
            if cand:
                ups.append((base + '/' + cand[0], rid)); fallback += 1
                continue
        left += 1
    c.executemany("update %s set %s=? where rowid=?" % (table, refcol), ups)
    print("  %-32s exact=%-6d fallback=%-6d left_local=%-6d" % (label, exact, fallback, left))
    return exact + fallback


NONHTTPS = "%s is not null and trim(%s)!='' and %s not like 'https://%%'"
tot = 0
# phrase audio (en/om) -> hybrid
tot += promote("generated_tts_audio[phrase]",
               "select rowid, entry_id, lang_code, file_path from generated_tts_audio "
               "where entry_type='phrase' and " + (NONHTTPS % ("file_path", "file_path", "file_path")),
               "generated_tts_audio", "file_path", hybrid=True)
# phrase translations (am/ar/fr/zh) -> hybrid
tot += promote("generated_phrase_translations",
               "select rowid, phrase_id, lang_code, tts_audio_url from generated_phrase_translations "
               "where " + (NONHTTPS % ("tts_audio_url", "tts_audio_url", "tts_audio_url")),
               "generated_phrase_translations", "tts_audio_url", hybrid=True)
# word audio -> exact only
tot += promote("generated_tts_audio[word]",
               "select rowid, entry_id, lang_code, file_path from generated_tts_audio "
               "where entry_type='word' and " + (NONHTTPS % ("file_path", "file_path", "file_path")),
               "generated_tts_audio", "file_path", hybrid=False)
tot += promote("generated_translations",
               "select rowid, word_id, lang_code, tts_audio_url from generated_translations "
               "where " + (NONHTTPS % ("tts_audio_url", "tts_audio_url", "tts_audio_url")),
               "generated_translations", "tts_audio_url", hybrid=False)
# oromo audio table -> exact only
tot += promote("audio",
               "select rowid, NULL, NULL, file_path from audio "
               "where " + (NONHTTPS % ("file_path", "file_path", "file_path")),
               "audio", "file_path", hybrid=False)

c.commit()
print("total rows promoted:", tot)
print("eligible phrases AFTER:", c.execute(ELIG).fetchone()[0])
c.execute("PRAGMA wal_checkpoint(TRUNCATE);")
c.close()
print("\nWrote", OUT_DB, "- ready to verify & deploy.")

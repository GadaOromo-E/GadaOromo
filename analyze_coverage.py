import os, re, sqlite3, boto3
from collections import defaultdict
from botocore.config import Config

env = {}
for line in open('.env', encoding='utf-8'):
    line = line.strip()
    if line and not line.startswith('#') and '=' in line:
        k, v = line.split('=', 1)
        env[k.strip()] = v.strip().strip('"').strip("'")
s3 = boto3.client('s3', endpoint_url=env['R2_ENDPOINT'].rstrip('/'),
                  aws_access_key_id=env['R2_ACCESS_KEY_ID'],
                  aws_secret_access_key=env['R2_SECRET_ACCESS_KEY'],
                  config=Config(signature_version='s3v4'), region_name='auto')
bucket = env['R2_BUCKET_NAME']


def canon(l):
    l = (l or "").lower().replace('_', '-')
    for pre, out in (('en', 'en'), ('am', 'am'), ('ar', 'ar'), ('fr', 'fr'),
                     ('zh', 'zh-cn'), ('om', 'om'), ('or', 'om')):
        if l.startswith(pre):
            return out
    return l


def bn(p):
    return os.path.basename((p or "").replace('\\', '/').strip())


# local files on disk
local = set(os.listdir('static/uploads'))
print("local files on disk:", len(local))

# R2 keys + phrase index
PHRASE_RE = re.compile(r'^tts_phrase_(\d+)_([A-Za-z-]+)_')
r2 = set(); r2_phrase = defaultdict(set)
tok = None
while True:
    kw = dict(Bucket=bucket, MaxKeys=1000)
    if tok: kw['ContinuationToken'] = tok
    r = s3.list_objects_v2(**kw)
    for o in r.get('Contents', []):
        k = o['Key']; r2.add(k)
        m = PHRASE_RE.match(k)
        if m: r2_phrase[int(m.group(1))].add(canon(m.group(2)))
    if r.get('IsTruncated'): tok = r.get('NextContinuationToken')
    else: break
print("R2 objects:", len(r2))

c = sqlite3.connect('gadaoromo.db')
approved = set(x[0] for x in c.execute(
    "select id from phrases where status='approved' and english is not null and trim(english)!=''"))
print("approved phrases:", len(approved))

# gather every phrase audio ref (en/om from generated_tts_audio, others from gpt)
refs = c.execute("""
  select entry_id, lower(replace(trim(lang_code),'_','-')), file_path
    from generated_tts_audio where entry_type='phrase' and file_path is not null and trim(file_path)!=''
  union all
  select phrase_id, lower(replace(trim(lang_code),'_','-')), tts_audio_url
    from generated_phrase_translations where tts_audio_url is not null and trim(tts_audio_url)!=''
""").fetchall()

# text translations available per phrase (so audio is actually usable/displayable)
txt = defaultdict(set)
txt[0].add('en')
for pid, in c.execute("select id from phrases where status='approved'"):
    txt[pid].add('en')  # english always present
for pid, lang in c.execute("select phrase_id, lower(replace(trim(lang_code),'_','-')) from generated_phrase_translations where translated_text is not null and trim(translated_text)!=''"):
    txt[pid].add(canon(lang))

in_r2 = defaultdict(set)        # langs playable now (file already in R2)
if_upload = defaultdict(set)    # langs playable if we upload existing local files too
need_gen = defaultdict(set)     # langs where a DB row exists but no file anywhere

for pid, lang, ref in refs:
    if pid not in approved: continue
    lang = canon(lang); key = bn(ref)
    has_r2 = (key in r2) or (lang in r2_phrase.get(pid, set()))
    has_local = key in local
    if has_r2:
        in_r2[pid].add(lang); if_upload[pid].add(lang)
    elif has_local:
        if_upload[pid].add(lang)
    else:
        need_gen[pid].add(lang)


def elig(d):
    return sum(1 for p in approved if len(d.get(p, set()) & {'en','am','ar','fr','zh-cn','om'}) >= 2)


print()
print("ELIGIBLE (>=2 langs) phrases:")
print("  audio already in R2 (deploy now):           ", elig(in_r2))
print("  IF we upload existing local files to R2:    ", elig(if_upload))
# phrases still short of 2 langs even after uploading locals
short = [p for p in approved if len(if_upload.get(p, set()) & {'en','am','ar','fr','zh-cn','om'}) < 2]
print("  phrases still < 2 langs after upload:       ", len(short))
# of those, how many at least have the TRANSLATION TEXT for >=2 langs (so only audio-gen is needed)
txt_ok = [p for p in short if len(txt.get(p, set()) & {'en','am','ar','fr','zh-cn','om'}) >= 2]
print("    ...of which have text in >=2 langs (gen audio only):", len(txt_ok))
print("    ...need translation text too:                       ", len(short) - len(txt_ok))

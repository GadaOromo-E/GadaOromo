import os, sqlite3, boto3
from botocore.config import Config

env = {}
for line in open('.env', encoding='utf-8'):
    line = line.strip()
    if not line or line.startswith('#') or '=' not in line:
        continue
    k, v = line.split('=', 1)
    env[k.strip()] = v.strip().strip('"').strip("'")

ak = env['R2_ACCESS_KEY_ID']; sk = env['R2_SECRET_ACCESS_KEY']
bucket = env['R2_BUCKET_NAME']; endpoint = env['R2_ENDPOINT'].rstrip('/')
base = env['R2_PUBLIC_BASE_URL'].rstrip('/')
print('bucket=', bucket, '| public_base=', base)

s3 = boto3.client('s3', endpoint_url=endpoint, aws_access_key_id=ak,
                  aws_secret_access_key=sk, config=Config(signature_version='s3v4'),
                  region_name='auto')

resp = s3.list_objects_v2(Bucket=bucket, MaxKeys=10)
print('KeyCount=', resp.get('KeyCount'), 'IsTruncated=', resp.get('IsTruncated'))
print('sample R2 keys:')
for o in resp.get('Contents', []):
    print('   ', o['Key'])


def bn(p):
    return os.path.basename(p.replace('\\', '/'))


c = sqlite3.connect('gadaoromo.db')
samples = []
for (fp,) in c.execute("select file_path from generated_tts_audio where file_path like '%uploads/%' limit 5"):
    samples.append(bn(fp))
for (fp,) in c.execute("select tts_audio_url from generated_phrase_translations where tts_audio_url like '%uploads/%' limit 5"):
    samples.append(bn(fp))

print('\nHEAD checks (basename -> exists in R2?):')
found = 0
for key in samples:
    try:
        s3.head_object(Bucket=bucket, Key=key)
        print('   FOUND   ', key); found += 1
    except Exception as e:
        code = getattr(e, 'response', {}).get('Error', {}).get('Code', '?')
        print('   MISSING(%s) %s' % (code, key))
print('\n%d/%d sampled basenames exist in R2' % (found, len(samples)))

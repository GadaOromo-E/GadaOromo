import os
import sqlite3
from pathlib import Path
from urllib.parse import urlparse

import boto3
from dotenv import load_dotenv

load_dotenv()

DB_PATH = os.getenv("DB_PATH") or os.getenv("DB_NAME") or "/data/gadaoromo.db"
UPLOAD_FOLDER = Path(os.getenv("UPLOAD_FOLDER") or "/data/uploads")
DRY_RUN = os.getenv("DRY_RUN", "true").lower() == "true"

R2_ENDPOINT = os.getenv("R2_ENDPOINT")
R2_ACCESS_KEY_ID = os.getenv("R2_ACCESS_KEY_ID")
R2_SECRET_ACCESS_KEY = os.getenv("R2_SECRET_ACCESS_KEY")
R2_BUCKET_NAME = os.getenv("R2_BUCKET_NAME")
R2_PUBLIC_BASE_URL = os.getenv("R2_PUBLIC_BASE_URL", "").rstrip("/")

AUDIO_EXTS = (".mp3", ".mpeg", ".wav", ".m4a", ".ogg")

client = boto3.client(
    "s3",
    endpoint_url=R2_ENDPOINT,
    aws_access_key_id=R2_ACCESS_KEY_ID,
    aws_secret_access_key=R2_SECRET_ACCESS_KEY,
    region_name="auto",
)

TARGETS = [
    ("generated_tts_audio", "id", "file_path"),
    ("generated_translations", "id", "tts_audio_url"),
    ("generated_phrase_translations", "id", "tts_audio_url"),
]

def is_remote(value: str) -> bool:
    return isinstance(value, str) and value.startswith(("http://", "https://"))

def is_local_audio_ref(value: str) -> bool:
    if not isinstance(value, str):
        return False
    v = value.strip()
    if not v or is_remote(v):
        return False
    return (
        v.startswith("/uploads/")
        or v.startswith("uploads/")
    ) and v.lower().endswith(AUDIO_EXTS)

def extract_filename(value: str) -> str:
    v = value.strip()
    parsed = urlparse(v)
    path = parsed.path if parsed.scheme else v
    path = path.lstrip("/")
    if path.startswith("uploads/"):
        path = path[len("uploads/"):]
    return path.replace("\\", "/")

def find_local_file(filename: str):
    candidates = [
        UPLOAD_FOLDER / filename,
        Path("/data/uploads") / filename,
        Path("C:/data/uploads") / filename,
        Path.cwd() / "static" / "uploads" / filename,
        Path.cwd() / "uploads" / filename,
    ]

    for p in candidates:
        if p.exists():
            return p

    return None

def upload_to_r2(filename: str):
    local_file = find_local_file(filename)

    if not local_file:
        print(f"MISS local file: {filename}")
        return None

    object_key = filename.replace("\\", "/")
    public_url = f"{R2_PUBLIC_BASE_URL}/{object_key}"

    if DRY_RUN:
        print(f"DRY upload: {local_file} -> {public_url}")
        return public_url

    content_type = "audio/mpeg"
    if object_key.lower().endswith(".wav"):
        content_type = "audio/wav"
    elif object_key.lower().endswith(".m4a"):
        content_type = "audio/mp4"
    elif object_key.lower().endswith(".ogg"):
        content_type = "audio/ogg"

    client.upload_file(
        str(local_file),
        R2_BUCKET_NAME,
        object_key,
        ExtraArgs={"ContentType": content_type},
    )

    print(f"UPLOADED: {object_key}")
    return public_url

def table_exists(cur, table):
    cur.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
        (table,),
    )
    return cur.fetchone() is not None

def column_exists(cur, table, column):
    cur.execute(f"PRAGMA table_info({table})")
    return any(row[1] == column for row in cur.fetchall())

def main():
    print(f"DB_PATH={DB_PATH}")
    print(f"UPLOAD_FOLDER={UPLOAD_FOLDER}")
    print(f"DRY_RUN={DRY_RUN}")
    print(f"R2_BUCKET_NAME={R2_BUCKET_NAME}")
    print(f"R2_PUBLIC_BASE_URL={R2_PUBLIC_BASE_URL}")

    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    total_updates = 0
    total_misses = 0
    total_skipped_remote = 0

    for table, pk, col in TARGETS:
        if not table_exists(cur, table):
            print(f"SKIP missing table: {table}")
            continue

        if not column_exists(cur, table, col):
            print(f"SKIP missing column: {table}.{col}")
            continue

        query = f"""
            SELECT {pk}, {col}
            FROM {table}
            WHERE {col} LIKE 'uploads/%'
               OR {col} LIKE '/uploads/%'
        """

        cur.execute(query)
        rows = cur.fetchall()

        print(f"\nTABLE {table}.{col}: candidates={len(rows)}")

        for row_id, value in rows:
            if not value:
                continue

            if is_remote(value):
                total_skipped_remote += 1
                continue

            if not is_local_audio_ref(value):
                continue

            filename = extract_filename(value)
            new_url = upload_to_r2(filename)

            if not new_url:
                total_misses += 1
                continue

            print(f"UPDATE {table}.{col} id={row_id}")
            print(f"  old: {value}")
            print(f"  new: {new_url}")

            if not DRY_RUN:
                cur.execute(
                    f"UPDATE {table} SET {col}=? WHERE {pk}=?",
                    (new_url, row_id),
                )

            total_updates += 1

    if not DRY_RUN:
        conn.commit()

    conn.close()

    print("\nDONE")
    print(f"updates={total_updates}")
    print(f"misses={total_misses}")
    print(f"skipped_remote={total_skipped_remote}")
    print(f"dry_run={DRY_RUN}")

if __name__ == "__main__":
    main()
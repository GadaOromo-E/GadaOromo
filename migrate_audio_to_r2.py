import os
import sqlite3
from pathlib import Path
from urllib.parse import urlparse

import boto3
from dotenv import load_dotenv

load_dotenv()

DB_PATH = os.getenv("DB_NAME") or "/data/gadaoromo.db"
UPLOAD_FOLDER = Path(os.getenv("UPLOAD_FOLDER") or "/data/uploads")

R2_ENDPOINT = os.getenv("R2_ENDPOINT")
R2_ACCESS_KEY_ID = os.getenv("R2_ACCESS_KEY_ID")
R2_SECRET_ACCESS_KEY = os.getenv("R2_SECRET_ACCESS_KEY")
R2_BUCKET_NAME = os.getenv("R2_BUCKET_NAME")
R2_PUBLIC_BASE_URL = os.getenv("R2_PUBLIC_BASE_URL", "").rstrip("/")

DRY_RUN = os.getenv("DRY_RUN", "true").lower() == "true"

client = boto3.client(
    "s3",
    endpoint_url=R2_ENDPOINT,
    aws_access_key_id=R2_ACCESS_KEY_ID,
    aws_secret_access_key=R2_SECRET_ACCESS_KEY,
    region_name="auto",
)

def is_audio_ref(value):
    if not isinstance(value, str):
        return False
    return "/uploads/" in value and value.lower().endswith((".mp3", ".mpeg", ".wav"))

def extract_filename(value):
    parsed = urlparse(value)
    path = parsed.path if parsed.scheme else value
    return path.split("/uploads/")[-1].lstrip("/")

def upload_to_r2(filename):
    local_file = UPLOAD_FOLDER / filename

    if not local_file.exists():
        print(f"MISS local file: {local_file}")
        return None

    object_key = filename.replace("\\", "/")
    public_url = f"{R2_PUBLIC_BASE_URL}/{object_key}"

    if DRY_RUN:
        print(f"DRY upload: {local_file} -> {public_url}")
        return public_url

    client.upload_file(
        str(local_file),
        R2_BUCKET_NAME,
        object_key,
        ExtraArgs={"ContentType": "audio/mpeg"},
    )

    print(f"UPLOADED: {object_key}")
    return public_url

def main():
    print(f"DB_PATH={DB_PATH}")
    print(f"UPLOAD_FOLDER={UPLOAD_FOLDER}")
    print(f"DRY_RUN={DRY_RUN}")

    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
    tables = [r[0] for r in cur.fetchall()]

    updates = 0

    for table in tables:
        cur.execute(f"PRAGMA table_info({table})")
        columns = cur.fetchall()

        text_columns = [
            col[1] for col in columns
            if str(col[2]).upper() in ("TEXT", "VARCHAR", "CHAR")
        ]

        if not text_columns:
            continue

        pk_cols = [col[1] for col in columns if col[5] == 1]
        if not pk_cols:
            continue

        pk = pk_cols[0]

        for col in text_columns:
            cur.execute(f"SELECT {pk}, {col} FROM {table} WHERE {col} LIKE '%/uploads/%'")
            rows = cur.fetchall()

            for row_id, value in rows:
                if not is_audio_ref(value):
                    continue

                filename = extract_filename(value)
                new_url = upload_to_r2(filename)

                if not new_url:
                    continue

                print(f"UPDATE {table}.{col} id={row_id}")
                print(f"  old: {value}")
                print(f"  new: {new_url}")

                if not DRY_RUN:
                    cur.execute(
                        f"UPDATE {table} SET {col}=? WHERE {pk}=?",
                        (new_url, row_id),
                    )

                updates += 1

    if not DRY_RUN:
        conn.commit()

    conn.close()
    print(f"DONE updates={updates} dry_run={DRY_RUN}")

if __name__ == "__main__":
    main()
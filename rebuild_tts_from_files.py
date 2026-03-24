import os
import sqlite3
import hashlib

DB_PATH = "gadaoromo.db"
UPLOAD_DIR = "static/uploads"

conn = sqlite3.connect(DB_PATH)
c = conn.cursor()

added = 0

for fname in os.listdir(UPLOAD_DIR):
    if not fname.startswith("tts_"):
        continue

    parts = fname.split("_")

    try:
        entry_type = parts[1]   # word / phrase
        entry_id = int(parts[2])
        lang_code = parts[3]
    except:
        continue

    file_path = f"uploads/{fname}"

    text_hash = hashlib.md5(fname.encode()).hexdigest()

    c.execute("""
        INSERT OR IGNORE INTO generated_tts_audio
        (entry_type, entry_id, lang_code, text_hash, voice_provider, voice_name, file_path)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (
        entry_type,
        entry_id,
        lang_code,
        text_hash,
        "azure",
        "restored",
        file_path
    ))

    added += 1

conn.commit()
conn.close()

print("Restored:", added)
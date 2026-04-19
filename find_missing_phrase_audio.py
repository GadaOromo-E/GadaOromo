# -*- coding: utf-8 -*-
"""
Created on Mon Apr 20 01:02:17 2026

@author: ademo
"""

import os
import sqlite3
from pathlib import Path

DB = r"C:\data\gadaoromo.db"
UPLOAD_DIR = Path(r"C:\data\uploads")
STATIC_DIR = Path(r"C:\Users\ademo\oromo_dictionary_clean\static\uploads")

conn = sqlite3.connect(DB)
cur = conn.cursor()

rows = cur.execute("""
    SELECT id, entry_id, lang_code, file_path
    FROM generated_tts_audio
    WHERE entry_type = 'phrase'
    ORDER BY entry_id, lang_code
""").fetchall()

missing = []
for row_id, entry_id, lang_code, file_path in rows:
    name = os.path.basename((file_path or "").replace("\\", "/"))
    if not name:
        missing.append((row_id, entry_id, lang_code, file_path, "empty_file_path"))
        continue

    p1 = UPLOAD_DIR / name
    p2 = STATIC_DIR / name

    if not p1.exists() and not p2.exists():
        missing.append((row_id, entry_id, lang_code, file_path, "missing_on_disk"))

print(f"Total phrase rows checked: {len(rows)}")
print(f"Missing phrase audio rows: {len(missing)}")

for item in missing[:50]:
    print(item)

with open("missing_phrase_audio_ids.txt", "w", encoding="utf-8") as f:
    for row_id, entry_id, lang_code, file_path, reason in missing:
        f.write(f"{row_id}\t{entry_id}\t{lang_code}\t{file_path}\t{reason}\n")

conn.close()
print("Saved: missing_phrase_audio_ids.txt")
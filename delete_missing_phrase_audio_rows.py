# -*- coding: utf-8 -*-
"""
Created on Mon Apr 20 01:06:33 2026

@author: ademo
"""

import sqlite3

DB = r"C:\data\gadaoromo.db"
IDS_FILE = "missing_phrase_audio_ids.txt"

ids = []
with open(IDS_FILE, "r", encoding="utf-8") as f:
    for line in f:
        parts = line.rstrip("\n").split("\t")
        if parts and parts[0].isdigit():
            ids.append(int(parts[0]))

print(f"Rows to delete: {len(ids)}")

if not ids:
    print("No rows to delete.")
    raise SystemExit

conn = sqlite3.connect(DB)
cur = conn.cursor()

cur.executemany(
    "DELETE FROM generated_tts_audio WHERE id = ?",
    [(i,) for i in ids]
)

conn.commit()
print(f"Deleted rows: {cur.rowcount}")
conn.close()
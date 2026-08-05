# -*- coding: utf-8 -*-
"""
Created on Sat Jul 18 18:15:05 2026

@author: ademo
"""

import sqlite3
import shutil

# Kopier databasefilen
shutil.copy2("railway_gadaoromo.db", "/data/gadaoromo.db")

# Verifiser
conn = sqlite3.connect("/data/gadaoromo.db")
cur = conn.cursor()

tables = [
    "approved_phrases",
    "phrase_translations",
    "generated_tts_audio",
]

for table in tables:
    cur.execute(f"SELECT COUNT(*) FROM {table}")
    print(table, cur.fetchone()[0])

conn.close()
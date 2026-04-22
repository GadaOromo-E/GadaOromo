import sqlite3

conn = sqlite3.connect(r"C:\data\gadaoromo.db")
c = conn.cursor()

print("Phrase audio rows:", c.execute("""
SELECT COUNT(*)
FROM generated_tts_audio
WHERE entry_type='phrase'
""").fetchone()[0])

print("Word audio rows:", c.execute("""
SELECT COUNT(*)
FROM generated_tts_audio
WHERE entry_type='word'
""").fetchone()[0])

conn.close()

import sqlite3

conn = sqlite3.connect(r"C:\data\gadaoromo.db")
c = conn.cursor()

print("Unique phrases with audio:", c.execute("""
SELECT COUNT(DISTINCT entry_id)
FROM generated_tts_audio
WHERE entry_type='phrase'
""").fetchone()[0])

conn.close()
import sqlite3

conn = sqlite3.connect(r"C:\data\gadaoromo.db")
c = conn.cursor()

for row in c.execute("""
SELECT lang_code, COUNT(*)
FROM generated_tts_audio
WHERE entry_type='phrase'
GROUP BY lang_code
ORDER BY lang_code
"""):
    print(row)

conn.close()
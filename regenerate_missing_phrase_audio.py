import sqlite3

db = r"C:\data\gadaoromo.db"
conn = sqlite3.connect(db)
cur = conn.cursor()

cur.execute("DELETE FROM generated_tts_audio WHERE entry_type='phrase'")
conn.commit()

print("Deleted phrase audio rows")

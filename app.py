# -*- coding: utf-8 -*-
"""
Created on Sun Jan 11 16:32:35 2026

@author: ademo
"""
#-*-coding: utf-8 -*-
"""
Full updated version of app.py (Flask + SQLite)

Features:
- Dictionary search + translate pages (DB lookup + word-by-word fallback)
- Admin login + dashboard + approve/reject
- Public submission:
    ✅ Words: manual + file upload (CSV/XLSX) on /submit (BOTH languages required)
    ✅ Phrases: manual + file upload (CSV/XLSX) on /submit_phrase (BOTH languages required)
- (Optional legacy) /submit_file kept for backward compatibility (still works)
- Admin bulk import (TXT/CSV/XLSX English-only) -> Google Translate -> pending
- Community audio upload + admin approve/reject
- NEW: In-page mic recording (Chrome/Edge) posts to:
    POST /api/submit-audio (multipart/form-data)
- Templates can hide mic automatically once Oromo audio is approved:
    approved_oromo_audio_word_ids
    approved_oromo_audio_phrase_ids

✅ NEW in this update:
- /admin/manage (Admin Management):
    - Keep add/delete admin
    - Add: Manage approved words (search + inline edit + permanent delete)
    - Add: Manage approved phrases (search + inline edit + permanent delete)
    - Deleting a word/phrase also deletes related audio rows and tries to remove audio files from disk.
- /admin/change_password route (template link support)

NOTES:
- Run on HTTPS (or localhost) for mic recording.
- Allowed audio: mp3, wav, m4a, webm, ogg
"""

import os
import re
import sqlite3
import logging
from uuid import uuid4
from difflib import get_close_matches

import requests
from flask import Flask, render_template, request, redirect, session, jsonify
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename

import csv
from io import StringIO, BytesIO
from openpyxl import load_workbook


# ------------------ APP SETUP ------------------

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "dev_only_change_me")

logging.basicConfig(level=logging.INFO)
app.logger.setLevel(logging.INFO)

BASE_DIR = os.path.abspath(os.path.dirname(__file__))
DEFAULT_DB = os.path.join(BASE_DIR, "gadaoromo.db")

# On Render: use disk path if it exists
RENDER_DISK_DB = "/var/data/gadaoromo.db"
DB_NAME = RENDER_DISK_DB if os.path.isdir("/var/data") else DEFAULT_DB


# ------------------ UPLOAD CONFIG (AUDIO) ------------------

if os.path.isdir("/var/data"):
    UPLOAD_FOLDER = "/var/data/uploads"
else:
    UPLOAD_FOLDER = os.path.join("static", "uploads")

os.makedirs(UPLOAD_FOLDER, exist_ok=True)

# Make uploaded audio available under /static/uploads on Render
if os.path.isdir("/var/data"):
    static_uploads = os.path.join(BASE_DIR, "static", "uploads")
    try:
        if os.path.islink(static_uploads) or os.path.exists(static_uploads):
            # if it's a real folder created before, leave it
            pass
        else:
            os.symlink(UPLOAD_FOLDER, static_uploads)
    except Exception as e:
        app.logger.warning(f"Could not create symlink for static/uploads: {e}")


ALLOWED_AUDIO = {"mp3", "wav", "m4a", "webm", "ogg"}

MAX_AUDIO_MB = 15
app.config["MAX_CONTENT_LENGTH"] = MAX_AUDIO_MB * 1024 * 1024


# ------------------ ADMIN IMPORT CONFIG ------------------

IMPORT_BATCH_SIZE = 200
IMPORT_MAX_CALLS = 10
IMPORT_MAX_WORDS = IMPORT_BATCH_SIZE * IMPORT_MAX_CALLS  # 2000


# ------------------ STOPWORDS ------------------

OROMO_STOP = {"fi", "kan", "inni", "isaan", "ani", "ati", "nu", "keessa", "irratti"}
EN_STOP = {"the", "is", "are", "to", "and", "of", "in", "on", "a", "an", "for", "with", "it", "this"}


# ------------------ TEXT NORMALIZATION ------------------

def normalize_text(text: str) -> str:
    t = (text or "").lower().strip()
    t = re.sub(r"[^\w\s]", " ", t)      # remove punctuation
    t = re.sub(r"\s+", " ", t).strip()  # collapse spaces
    return t

def normalize_tokens(text: str):
    t = normalize_text(text)
    return t.split() if t else []

def dedup_preserve_order(items):
    seen = set()
    out = []
    for x in items:
        if x not in seen:
            seen.add(x)
            out.append(x)
    return out


# ------------------ COMMUNITY FILE PARSERS (NO GOOGLE) ------------------

def parse_csv_pairs(file_bytes: bytes):
    """
    CSV must include headers: english,oromo (case-insensitive).
    Every row must contain BOTH values.
    """
    text = file_bytes.decode("utf-8", errors="replace")
    f = StringIO(text)
    reader = csv.DictReader(f)

    out = []
    for row in reader:
        en = normalize_text((row.get("english") or row.get("English") or "").strip())
        om = normalize_text((row.get("oromo") or row.get("Oromo") or "").strip())
        if en or om:
            out.append((en, om))

    seen = set()
    final = []
    for en, om in out:
        if en and en not in seen:
            seen.add(en)
            final.append((en, om))
    return final

def parse_xlsx_pairs(file_bytes: bytes):
    """
    XLSX format:
      Column A = English
      Column B = Oromo
    First row can be headers.
    """
    wb = load_workbook(BytesIO(file_bytes))
    ws = wb.active

    out = []
    for idx, row in enumerate(ws.iter_rows(values_only=True)):
        if not row:
            continue

        a = (row[0] if len(row) > 0 else "") or ""
        b = (row[1] if len(row) > 1 else "") or ""

        if idx == 0 and str(a).strip().lower() in ("english", "en") and str(b).strip().lower() in ("oromo", "om"):
            continue

        en = normalize_text(str(a))
        om = normalize_text(str(b))
        if en or om:
            out.append((en, om))

    seen = set()
    final = []
    for en, om in out:
        if en and en not in seen:
            seen.add(en)
            final.append((en, om))
    return final


# ------------------ ADMIN IMPORT PARSERS (ENGLISH-ONLY) ------------------

def parse_txt_english(file_bytes: bytes):
    """TXT: one English word per line."""
    text = file_bytes.decode("utf-8", errors="replace")
    words = []
    for line in text.splitlines():
        w = normalize_text(line)
        if w:
            words.append(w)
    return dedup_preserve_order(words)

def parse_csv_english(file_bytes: bytes):
    """CSV: prefer header 'english' else first column."""
    text = file_bytes.decode("utf-8", errors="replace")
    f = StringIO(text)
    reader = csv.DictReader(f)

    if not reader.fieldnames:
        return []

    english_key = None
    for k in reader.fieldnames:
        if (k or "").strip().lower() == "english":
            english_key = k
            break

    first_key = reader.fieldnames[0]

    words = []
    for row in reader:
        raw = row.get(english_key, "") if english_key else row.get(first_key, "")
        w = normalize_text(raw or "")
        if w:
            words.append(w)

    return dedup_preserve_order(words)

def parse_xlsx_english(file_bytes: bytes):
    """XLSX: Column A = English, optional header in first row."""
    wb = load_workbook(BytesIO(file_bytes))
    ws = wb.active

    words = []
    for idx, row in enumerate(ws.iter_rows(values_only=True)):
        if not row:
            continue
        a = (row[0] if len(row) > 0 else "") or ""

        if idx == 0 and str(a).strip().lower() in ("english", "en"):
            continue

        w = normalize_text(str(a))
        if w:
            words.append(w)

    return dedup_preserve_order(words)


# ------------------ ADMIN HELPER ------------------

def require_admin() -> bool:
    return "admin" in session

def _admin_id() -> int:
    try:
        return int(session.get("admin"))
    except Exception:
        return 0


# ------------------ GOOGLE TRANSLATE (CLOUD v2) ------------------

def _get_google_key() -> str:
    return os.environ.get("GOOGLE_TRANSLATE_API_KEY", "").strip()

def google_translate_batch_v2(texts, target: str, source: str = "en"):
    api_key = _get_google_key()
    if not api_key:
        app.logger.error("GOOGLE_TRANSLATE_API_KEY is missing at runtime!")
        return []

    if not texts:
        return []

    url = "https://translation.googleapis.com/language/translate/v2"
    payload = {"q": texts, "source": source, "target": target, "format": "text"}

    try:
        r = requests.post(url, params={"key": api_key}, json=payload, timeout=30)
        if r.status_code != 200:
            app.logger.error(f"Google Translate HTTP {r.status_code}: {(r.text or '')[:250]}")
            return []

        data = r.json()
        if isinstance(data, dict) and "error" in data:
            app.logger.error(f"Google Translate JSON error: {data.get('error')}")
            return []

        translations = data["data"]["translations"]
        return [normalize_text(t.get("translatedText", "")) for t in translations]

    except Exception as e:
        app.logger.exception(f"Google Translate exception: {repr(e)}")
        return []


# ------------------ AUDIO HELPERS ------------------

def allowed_audio(filename: str) -> bool:
    if not filename or "." not in filename:
        return False
    ext = filename.rsplit(".", 1)[1].lower()
    return ext in ALLOWED_AUDIO

def get_approved_audio(entry_type: str, entry_id: int) -> dict:
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("""
        SELECT lang, file_path
        FROM audio
        WHERE status='approved' AND entry_type=? AND entry_id=?
        ORDER BY id DESC
    """, (entry_type, entry_id))
    rows = c.fetchall()
    conn.close()

    out = {}
    for lang, path in rows:
        if lang not in out:
            out[lang] = path
    return out

def get_approved_oromo_audio_ids(entry_type: str) -> set:
    if entry_type not in ("word", "phrase"):
        return set()

    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("""
        SELECT DISTINCT entry_id
        FROM audio
        WHERE status='approved'
          AND entry_type=?
          AND lang='oromo'
    """, (entry_type,))
    ids = {r[0] for r in c.fetchall()}
    conn.close()
    return ids

def _audio_abs_path(file_path: str) -> str:
    """
    file_path is stored like: 'uploads/xyz.webm'
    If running on Render disk: audio is in /var/data/uploads/xyz.webm
    Else: audio is in static/uploads/xyz.webm
    """
    fp = (file_path or "").replace("\\", "/").strip()
    if not fp:
        return ""
    name = fp.split("/")[-1]  # xyz.webm
    return os.path.join(UPLOAD_FOLDER, name)

def delete_audio_for_entry(entry_type: str, entry_id: int):
    """
    Delete all audio rows for an entry and try to delete files from disk.
    """
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("SELECT id, file_path FROM audio WHERE entry_type=? AND entry_id=?", (entry_type, entry_id))
    rows = c.fetchall()

    # delete db rows first
    c.execute("DELETE FROM audio WHERE entry_type=? AND entry_id=?", (entry_type, entry_id))
    conn.commit()
    conn.close()

    # then delete files best-effort
    for _aid, fp in rows:
        abs_path = _audio_abs_path(fp)
        if abs_path and os.path.isfile(abs_path):
            try:
                os.remove(abs_path)
            except Exception:
                app.logger.exception(f"Could not delete audio file: {abs_path}")


# ------------------ DATABASE SETUP ------------------

def init_db():
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()

    c.execute("""
        CREATE TABLE IF NOT EXISTS words (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            english TEXT,
            oromo TEXT,
            status TEXT
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS phrases (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            english TEXT,
            oromo TEXT,
            status TEXT
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS admin (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT,
            password TEXT
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS search_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            query TEXT NOT NULL,
            direction TEXT,
            is_phrase INTEGER DEFAULT 0,
            is_exact INTEGER DEFAULT 0,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS search_counts (
            query TEXT PRIMARY KEY,
            total_count INTEGER DEFAULT 0,
            today_count INTEGER DEFAULT 0,
            week_count INTEGER DEFAULT 0,
            last_searched_at DATETIME
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS audio (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            entry_type TEXT,
            entry_id INTEGER,
            lang TEXT,
            file_path TEXT,
            status TEXT
        )
    """)

    conn.commit()
    conn.close()

init_db()


# ------------------ ANALYTICS HELPERS ------------------

def record_search(raw_query: str, direction: str, is_phrase: int, is_exact: int):
    q = normalize_text(raw_query)
    if not q:
        return

    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()

    c.execute(
        "INSERT INTO search_logs (query, direction, is_phrase, is_exact) VALUES (?, ?, ?, ?)",
        (q, direction, int(is_phrase), int(is_exact))
    )

    c.execute("SELECT total_count FROM search_counts WHERE query=?", (q,))
    row = c.fetchone()

    if row:
        c.execute("""
            UPDATE search_counts
            SET total_count = total_count + 1,
                today_count = today_count + 1,
                week_count = week_count + 1,
                last_searched_at = CURRENT_TIMESTAMP
            WHERE query=?
        """, (q,))
    else:
        c.execute("""
            INSERT INTO search_counts (query, total_count, today_count, week_count, last_searched_at)
            VALUES (?, 1, 1, 1, CURRENT_TIMESTAMP)
        """, (q,))

    conn.commit()
    conn.close()

def get_trending(limit=20):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("""
        SELECT query, today_count, week_count, total_count
        FROM search_counts
        ORDER BY today_count DESC, week_count DESC, total_count DESC
        LIMIT ?
    """, (limit,))
    rows = c.fetchall()
    conn.close()
    return rows


# ------------------ SUGGESTIONS ------------------

def suggest_terms(term: str, direction: str, limit: int = 8):
    t = normalize_text(term)
    if not t:
        return {"closest": [], "prefix": [], "partial": []}

    col = "oromo" if direction == "om_en" else "english"

    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()

    c.execute(f"""
        SELECT {col} FROM words
        WHERE status='approved' AND {col} LIKE ?
        LIMIT ?
    """, (t + "%", limit))
    prefix = [r[0] for r in c.fetchall()]

    c.execute(f"""
        SELECT {col} FROM words
        WHERE status='approved' AND {col} LIKE ?
        LIMIT ?
    """, ("%" + t + "%", limit))
    partial = [r[0] for r in c.fetchall()]

    c.execute(f"""
        SELECT {col} FROM words
        WHERE status='approved'
        ORDER BY id DESC
        LIMIT 3000
    """)
    candidates = [r[0] for r in c.fetchall()]
    conn.close()

    closest = get_close_matches(t, candidates, n=limit, cutoff=0.75)

    def dedup(seq):
        seen = set()
        out = []
        for x in seq:
            if x not in seen:
                seen.add(x)
                out.append(x)
        return out

    return {"closest": dedup(closest), "prefix": dedup(prefix), "partial": dedup(partial)}


# ------------------ AUTO LANGUAGE DETECT ------------------

def detect_direction_auto(text: str) -> str:
    t = normalize_text(text)
    tokens = t.split()
    if not tokens:
        return "en_om"

    filtered = [w for w in tokens if w not in EN_STOP and w not in OROMO_STOP]
    if not filtered:
        filtered = tokens

    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()

    or_score = 0
    en_score = 0

    for w in filtered:
        c.execute("SELECT 1 FROM words WHERE status='approved' AND oromo=?", (w,))
        if c.fetchone():
            or_score += 1

        c.execute("SELECT 1 FROM words WHERE status='approved' AND english=?", (w,))
        if c.fetchone():
            en_score += 1

    c.execute("SELECT 1 FROM phrases WHERE status='approved' AND oromo=?", (t,))
    if c.fetchone():
        or_score += 4

    c.execute("SELECT 1 FROM phrases WHERE status='approved' AND english=?", (t,))
    if c.fetchone():
        en_score += 4

    conn.close()

    if or_score > en_score + 0.5:
        return "om_en"
    if en_score > or_score + 0.5:
        return "en_om"
    return "en_om"


# ------------------ TRANSLATION LOGIC ------------------

def translate_text(text: str, direction: str = "om_en"):
    t = normalize_text(text)
    if not t:
        return "", 0, 0

    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()

    # Phrase exact match
    if direction == "om_en":
        c.execute("SELECT id, english FROM phrases WHERE status='approved' AND oromo=?", (t,))
        row = c.fetchone()
        if row:
            conn.close()
            return row[1], 1, 1
    else:
        c.execute("SELECT id, oromo FROM phrases WHERE status='approved' AND english=?", (t,))
        row = c.fetchone()
        if row:
            conn.close()
            return row[1], 1, 1

    tokens = t.split()
    if len(tokens) == 1:
        # Word exact match
        if direction == "om_en":
            c.execute("SELECT id, english FROM words WHERE status='approved' AND oromo=?", (t,))
            row = c.fetchone()
            if row:
                conn.close()
                return row[1], 1, 0
        else:
            c.execute("SELECT id, oromo FROM words WHERE status='approved' AND english=?", (t,))
            row = c.fetchone()
            if row:
                conn.close()
                return row[1], 1, 0

    # Word-by-word fallback
    out = []
    for w in tokens:
        if direction == "om_en":
            c.execute("SELECT english FROM words WHERE status='approved' AND oromo=?", (w,))
            r = c.fetchone()
            out.append(r[0] if r else w)
        else:
            c.execute("SELECT oromo FROM words WHERE status='approved' AND english=?", (w,))
            r = c.fetchone()
            out.append(r[0] if r else w)

    conn.close()
    return " ".join(out), 0, 0


# ------------------ HOME PAGE ------------------

@app.route("/", methods=["GET", "POST"])
def home():
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()

    result = None
    result_id = None
    suggestions = None
    audio = None

    if request.method == "POST":
        word = normalize_text(request.form.get("word", ""))

        c.execute("""
            SELECT id, english, oromo
            FROM words
            WHERE status='approved' AND (english=? OR oromo=?)
        """, (word, word))
        row = c.fetchone()

        if row:
            result_id = row[0]
            result = (row[1], row[2])
            audio = get_approved_audio("word", result_id)

        if not row and word:
            suggestions = {
                "en": suggest_terms(word, "en_om"),
                "om": suggest_terms(word, "om_en")
            }

    c.execute("SELECT id, english, oromo FROM words WHERE status='approved' ORDER BY english ASC")
    all_words = c.fetchall()
    conn.close()

    trending = get_trending(limit=15)
    approved_oromo_audio_word_ids = get_approved_oromo_audio_ids("word")

    return render_template(
        "index.html",
        result=result,
        result_id=result_id,
        audio=audio,
        words=all_words,
        suggestions=suggestions,
        trending=trending,
        approved_oromo_audio_word_ids=approved_oromo_audio_word_ids
    )


# ------------------ TRANSLATOR PAGE ------------------

@app.route("/translate", methods=["GET", "POST"])
def translate():
    result = None
    text = ""
    direction = "auto"
    suggestions = None
    audio = None
    matched = None

    if request.method == "POST":
        text = request.form.get("text", "")
        direction = request.form.get("direction", "auto")

        if direction == "auto":
            direction = detect_direction_auto(text)

        clean = normalize_text(text)

        conn = sqlite3.connect(DB_NAME)
        c = conn.cursor()

        if clean:
            if direction == "om_en":
                c.execute("SELECT id FROM phrases WHERE status='approved' AND oromo=?", (clean,))
            else:
                c.execute("SELECT id FROM phrases WHERE status='approved' AND english=?", (clean,))
            pr = c.fetchone()
            if pr:
                matched = {"type": "phrase", "id": pr[0]}
                audio = get_approved_audio("phrase", pr[0])

        if not matched and clean and len(clean.split()) == 1:
            if direction == "om_en":
                c.execute("SELECT id FROM words WHERE status='approved' AND oromo=?", (clean,))
            else:
                c.execute("SELECT id FROM words WHERE status='approved' AND english=?", (clean,))
            wr = c.fetchone()
            if wr:
                matched = {"type": "word", "id": wr[0]}
                audio = get_approved_audio("word", wr[0])

        conn.close()

        translated, is_exact, is_phrase = translate_text(text, direction)
        record_search(text, direction, is_phrase, is_exact)
        result = translated

        if clean and not is_exact and len(clean.split()) == 1:
            suggestions = suggest_terms(clean, direction)

    trending = get_trending(limit=15)
    approved_oromo_audio_phrase_ids = get_approved_oromo_audio_ids("phrase")
    approved_oromo_audio_word_ids = get_approved_oromo_audio_ids("word")

    return render_template(
        "translate.html",
        result=result,
        text=text,
        direction=direction,
        suggestions=suggestions,
        trending=trending,
        matched=matched,
        audio=audio,
        approved_oromo_audio_word_ids=approved_oromo_audio_word_ids,
        approved_oromo_audio_phrase_ids=approved_oromo_audio_phrase_ids
    )


# ------------------ PUBLIC SUBMISSION (WORDS) - MANUAL + FILE ------------------

@app.route("/submit", methods=["GET", "POST"])
def submit():
    msg = None

    if request.method == "POST":
        mode = (request.form.get("mode") or "").strip().lower()

        f = request.files.get("file")
        if mode == "file" or (f and f.filename):
            if not f or not f.filename:
                msg = "Please choose a CSV or XLSX file."
                return render_template("submit.html", msg=msg)

            filename = (f.filename or "").lower().strip()
            data = f.read()

            try:
                if filename.endswith(".csv"):
                    pairs = parse_csv_pairs(data)
                elif filename.endswith(".xlsx"):
                    pairs = parse_xlsx_pairs(data)
                else:
                    msg = "Only .csv or .xlsx files are allowed."
                    return render_template("submit.html", msg=msg)
            except Exception as e:
                app.logger.exception(f"submit (words) file parse error: {repr(e)}")
                msg = "Could not read the file. Please check its format."
                return render_template("submit.html", msg=msg)

            if not pairs:
                msg = "No rows found in the file."
                return render_template("submit.html", msg=msg)

            for en, om in pairs:
                if not en or not om:
                    msg = "Rejected: Every row must include BOTH English and Oromo (no English-only rows)."
                    return render_template("submit.html", msg=msg)

            inserted = 0
            skipped = 0

            conn = sqlite3.connect(DB_NAME)
            c = conn.cursor()

            for en, om in pairs:
                c.execute("SELECT 1 FROM words WHERE english=? OR oromo=? LIMIT 1", (en, om))
                if c.fetchone():
                    skipped += 1
                    continue
                c.execute("INSERT INTO words (english, oromo, status) VALUES (?, ?, 'pending')", (en, om))
                inserted += 1

            conn.commit()
            conn.close()

            msg = f"Thanks! File submitted. Added: {inserted} | Skipped duplicates: {skipped}. Waiting for admin approval."
            return render_template("submit.html", msg=msg)

        english = normalize_text(request.form.get("english", ""))
        oromo = normalize_text(request.form.get("oromo", ""))

        if not english or not oromo:
            msg = "Please provide both English and Oromo."
            return render_template("submit.html", msg=msg)

        conn = sqlite3.connect(DB_NAME)
        c = conn.cursor()

        c.execute("SELECT 1 FROM words WHERE english=? OR oromo=?", (english, oromo))
        if c.fetchone():
            conn.close()
            msg = "This word already exists (or is pending). Try another."
            return render_template("submit.html", msg=msg)

        c.execute("INSERT INTO words (english, oromo, status) VALUES (?, ?, 'pending')", (english, oromo))
        conn.commit()
        conn.close()

        msg = "Thank you! Your word is waiting for admin approval."
        return render_template("submit.html", msg=msg)

    return render_template("submit.html", msg=msg)


# ------------------ PUBLIC SUBMISSION (PHRASES) + FILE UPLOAD ------------------

@app.route("/submit_phrase", methods=["GET", "POST"])
def submit_phrase():
    msg = None

    if request.method == "POST":
        mode = (request.form.get("mode") or "").strip().lower()

        f = request.files.get("file")
        if mode == "file" or (f and f.filename):
            if not f or not f.filename:
                msg = "Please choose a CSV or XLSX file."
                return render_template("submit_phrase.html", msg=msg)

            filename = (f.filename or "").lower().strip()
            data = f.read()

            try:
                if filename.endswith(".csv"):
                    pairs = parse_csv_pairs(data)
                elif filename.endswith(".xlsx"):
                    pairs = parse_xlsx_pairs(data)
                else:
                    msg = "Only .csv or .xlsx files are allowed."
                    return render_template("submit_phrase.html", msg=msg)
            except Exception as e:
                app.logger.exception(f"submit_phrase file parse error: {repr(e)}")
                msg = "Could not read the file. Please check its format."
                return render_template("submit_phrase.html", msg=msg)

            if not pairs:
                msg = "No rows found in the file."
                return render_template("submit_phrase.html", msg=msg)

            for en, om in pairs:
                if not en or not om:
                    msg = "Rejected: Every row must include BOTH English and Oromo (no English-only rows)."
                    return render_template("submit_phrase.html", msg=msg)

            inserted = 0
            skipped = 0

            conn = sqlite3.connect(DB_NAME)
            c = conn.cursor()

            for en, om in pairs:
                c.execute("SELECT 1 FROM phrases WHERE english=? OR oromo=? LIMIT 1", (en, om))
                if c.fetchone():
                    skipped += 1
                    continue
                c.execute("INSERT INTO phrases (english, oromo, status) VALUES (?, ?, 'pending')", (en, om))
                inserted += 1

            conn.commit()
            conn.close()

            msg = f"Thanks! Phrase file submitted. Added: {inserted} | Skipped duplicates: {skipped}. Waiting for admin approval."
            return render_template("submit_phrase.html", msg=msg)

        english = normalize_text(request.form.get("english", ""))
        oromo = normalize_text(request.form.get("oromo", ""))

        if not english or not oromo:
            msg = "Please provide both English and Oromo phrase."
            return render_template("submit_phrase.html", msg=msg)

        conn = sqlite3.connect(DB_NAME)
        c = conn.cursor()

        c.execute("SELECT 1 FROM phrases WHERE english=? OR oromo=?", (english, oromo))
        if c.fetchone():
            conn.close()
            msg = "This phrase already exists (or is pending). Try another."
            return render_template("submit_phrase.html", msg=msg)

        c.execute("INSERT INTO phrases (english, oromo, status) VALUES (?, ?, 'pending')", (english, oromo))
        conn.commit()
        conn.close()

        msg = "Thank you! Your phrase is waiting for admin approval."
        return render_template("submit_phrase.html", msg=msg)

    return render_template("submit_phrase.html", msg=msg)


# ------------------ (LEGACY) COMMUNITY FILE SUBMISSION ------------------

@app.route("/submit_file", methods=["GET", "POST"])
def submit_file():
    msg = None

    if request.method == "POST":
        f = request.files.get("file")
        if not f or not f.filename:
            msg = "Please choose a file."
            return render_template("submit_file.html", msg=msg)

        filename = (f.filename or "").lower().strip()
        data = f.read()

        try:
            if filename.endswith(".csv"):
                pairs = parse_csv_pairs(data)
            elif filename.endswith(".xlsx"):
                pairs = parse_xlsx_pairs(data)
            else:
                msg = "Only .csv or .xlsx files are allowed."
                return render_template("submit_file.html", msg=msg)
        except Exception as e:
            app.logger.exception(f"submit_file parse error: {repr(e)}")
            msg = "Could not read the file. Please check its format."
            return render_template("submit_file.html", msg=msg)

        if not pairs:
            msg = "No rows found in the file."
            return render_template("submit_file.html", msg=msg)

        for en, om in pairs:
            if not en or not om:
                msg = "Rejected: Every row must include BOTH English and Oromo (community cannot submit English-only)."
                return render_template("submit_file.html", msg=msg)

        inserted = 0
        skipped = 0

        conn = sqlite3.connect(DB_NAME)
        c = conn.cursor()

        for en, om in pairs:
            c.execute("SELECT 1 FROM words WHERE english=? OR oromo=? LIMIT 1", (en, om))
            if c.fetchone():
                skipped += 1
                continue
            c.execute("INSERT INTO words (english, oromo, status) VALUES (?, ?, 'pending')", (en, om))
            inserted += 1

        conn.commit()
        conn.close()

        msg = f"Thanks! File submitted. Added: {inserted} | Skipped duplicates: {skipped}. Waiting for admin approval."
        return render_template("submit_file.html", msg=msg)

    return render_template("submit_file.html", msg=msg)


# ------------------ API AUDIO SUBMISSION ------------------

@app.route("/api/submit-audio", methods=["POST"])
def api_submit_audio():
    entry_type = (request.form.get("entry_type") or "").strip().lower()
    entry_id_raw = (request.form.get("entry_id") or "").strip()
    lang = (request.form.get("lang") or "oromo").strip().lower()

    if entry_type not in ("word", "phrase"):
        return jsonify({"ok": False, "error": "Invalid entry_type"}), 400
    if lang not in ("oromo", "english"):
        return jsonify({"ok": False, "error": "Invalid lang"}), 400
    if not entry_id_raw.isdigit():
        return jsonify({"ok": False, "error": "Invalid entry_id"}), 400

    entry_id = int(entry_id_raw)

    f = request.files.get("audio")
    if not f or not f.filename:
        return jsonify({"ok": False, "error": "Missing audio file"}), 400
    if not allowed_audio(f.filename):
        return jsonify({"ok": False, "error": "Allowed audio: mp3, wav, m4a, webm, ogg"}), 400

    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    if entry_type == "word":
        c.execute("SELECT id FROM words WHERE id=? AND status='approved'", (entry_id,))
    else:
        c.execute("SELECT id FROM phrases WHERE id=? AND status='approved'", (entry_id,))
    row = c.fetchone()
    if not row:
        conn.close()
        return jsonify({"ok": False, "error": "Entry not found or not approved"}), 404

    original = secure_filename(f.filename)
    ext = original.rsplit(".", 1)[1].lower()

    new_name = f"{entry_type}_{entry_id}_{lang}_{uuid4().hex}.{ext}"
    save_path = os.path.join(UPLOAD_FOLDER, new_name)
    f.save(save_path)

    rel_path = f"uploads/{new_name}"

    c.execute("""
        INSERT INTO audio (entry_type, entry_id, lang, file_path, status)
        VALUES (?, ?, ?, ?, 'pending')
    """, (entry_type, entry_id, lang, rel_path))
    conn.commit()
    conn.close()

    return jsonify({"ok": True, "message": "Audio submitted for admin approval."})


# ------------------ COMMUNITY AUDIO UPLOAD ------------------

@app.route("/upload_audio/<entry_type>/<int:entry_id>/<lang>", methods=["GET", "POST"])
def upload_audio(entry_type, entry_id, lang):
    if entry_type not in ("word", "phrase"):
        return "Invalid entry type", 400
    if lang not in ("oromo", "english"):
        return "Invalid language", 400

    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    if entry_type == "word":
        c.execute("SELECT id, english, oromo FROM words WHERE id=? AND status='approved'", (entry_id,))
    else:
        c.execute("SELECT id, english, oromo FROM phrases WHERE id=? AND status='approved'", (entry_id,))
    row = c.fetchone()
    conn.close()

    if not row:
        return "Entry not found or not approved.", 404

    if request.method == "POST":
        f = request.files.get("audio")
        if not f or not f.filename:
            return "Please choose an audio file.", 400
        if not allowed_audio(f.filename):
            return "Allowed audio: mp3, wav, m4a, webm, ogg", 400

        original = secure_filename(f.filename)
        ext = original.rsplit(".", 1)[1].lower()

        new_name = f"{entry_type}_{entry_id}_{lang}_{uuid4().hex}.{ext}"
        save_path = os.path.join(UPLOAD_FOLDER, new_name)
        f.save(save_path)

        rel_path = f"uploads/{new_name}"

        conn = sqlite3.connect(DB_NAME)
        c = conn.cursor()
        c.execute("""
            INSERT INTO audio (entry_type, entry_id, lang, file_path, status)
            VALUES (?, ?, ?, ?, 'pending')
        """, (entry_type, entry_id, lang, rel_path))
        conn.commit()
        conn.close()

        return "Thanks! Audio submitted for admin approval."

    return render_template(
        "upload_audio.html",
        entry_type=entry_type,
        entry_id=entry_id,
        lang=lang,
        english=row[1],
        oromo=row[2]
    )


# ------------------ ADMIN LOGIN ------------------

@app.route("/admin", methods=["GET", "POST"])
def admin_login():
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")

        conn = sqlite3.connect(DB_NAME)
        c = conn.cursor()
        c.execute("SELECT id, password FROM admin WHERE email=?", (email,))
        admin_row = c.fetchone()
        conn.close()

        if admin_row and check_password_hash(admin_row[1], password):
            session["admin"] = admin_row[0]
            return redirect("/dashboard")

        return "Invalid login"

    return render_template("admin_login.html")


# ------------------ ADMIN DASHBOARD ------------------

@app.route("/dashboard")
def dashboard():
    if not require_admin():
        return redirect("/admin")

    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()

    c.execute("SELECT id, english, oromo FROM words WHERE status='pending' ORDER BY id DESC")
    pending_words = c.fetchall()

    c.execute("SELECT id, english, oromo FROM phrases WHERE status='pending' ORDER BY id DESC")
    pending_phrases = c.fetchall()

    c.execute("""
        SELECT id, entry_type, entry_id, lang, file_path
        FROM audio
        WHERE status='pending'
        ORDER BY id DESC
    """)
    pending_audio = c.fetchall()

    c.execute("SELECT id, english, oromo FROM words WHERE status='approved'")
    words_lookup = {row[0]: (row[1], row[2]) for row in c.fetchall()}

    c.execute("SELECT id, english, oromo FROM phrases WHERE status='approved'")
    phrases_lookup = {row[0]: (row[1], row[2]) for row in c.fetchall()}

    conn.close()

    return render_template(
        "admin_dashboard.html",
        pending=pending_words,
        pending_phrases=pending_phrases,
        pending_audio=pending_audio,
        words_lookup=words_lookup,
        phrases_lookup=phrases_lookup
    )


# ------------------ ADMIN MANAGEMENT: ADMINS + EDIT/DELETE WORDS/PHRASES ------------------

@app.route("/admin/manage", methods=["GET", "POST"])
def admin_manage():
    if not require_admin():
        return redirect("/admin")

    msg = None

    if request.method == "POST":
        action = (request.form.get("action") or "").strip()

        # --- Admin actions ---
        if action == "add_admin":
            email = (request.form.get("email") or "").strip().lower()
            password = request.form.get("password") or ""
            if not email or not password:
                msg = "Email and password are required."
            else:
                conn = sqlite3.connect(DB_NAME)
                c = conn.cursor()
                c.execute("SELECT 1 FROM admin WHERE email=?", (email,))
                if c.fetchone():
                    msg = "Admin already exists with that email."
                else:
                    c.execute("INSERT INTO admin (email, password) VALUES (?, ?)", (email, generate_password_hash(password)))
                    conn.commit()
                    msg = "Admin added."
                conn.close()

        elif action == "delete_admin":
            admin_id_raw = (request.form.get("admin_id") or "").strip()
            if not admin_id_raw.isdigit():
                msg = "Invalid admin id."
            else:
                admin_id = int(admin_id_raw)
                if admin_id == _admin_id():
                    msg = "You cannot delete your own account."
                else:
                    conn = sqlite3.connect(DB_NAME)
                    c = conn.cursor()
                    c.execute("DELETE FROM admin WHERE id=?", (admin_id,))
                    conn.commit()
                    conn.close()
                    msg = "Admin deleted."

        # --- Words actions ---
        elif action == "update_word":
            wid_raw = (request.form.get("word_id") or "").strip()
            en = normalize_text(request.form.get("english") or "")
            om = normalize_text(request.form.get("oromo") or "")
            if not wid_raw.isdigit():
                msg = "Invalid word id."
            elif not en or not om:
                msg = "Both English and Oromo are required."
            else:
                wid = int(wid_raw)
                conn = sqlite3.connect(DB_NAME)
                c = conn.cursor()

                # must exist and be approved
                c.execute("SELECT 1 FROM words WHERE id=? AND status='approved'", (wid,))
                if not c.fetchone():
                    msg = "Word not found (or not approved)."
                else:
                    # avoid duplicates (other rows)
                    c.execute("""
                        SELECT 1 FROM words
                        WHERE id != ? AND (english=? OR oromo=?)
                        LIMIT 1
                    """, (wid, en, om))
                    if c.fetchone():
                        msg = "Duplicate conflict: another word already uses that English or Oromo."
                    else:
                        c.execute("UPDATE words SET english=?, oromo=? WHERE id=?", (en, om, wid))
                        conn.commit()
                        msg = "Word updated."
                conn.close()

        elif action == "delete_word":
            wid_raw = (request.form.get("word_id") or "").strip()
            if not wid_raw.isdigit():
                msg = "Invalid word id."
            else:
                wid = int(wid_raw)

                # delete audio first
                delete_audio_for_entry("word", wid)

                conn = sqlite3.connect(DB_NAME)
                c = conn.cursor()
                c.execute("DELETE FROM words WHERE id=? AND status='approved'", (wid,))
                conn.commit()
                conn.close()
                msg = "Word deleted permanently."

        # --- Phrases actions ---
        elif action == "update_phrase":
            pid_raw = (request.form.get("phrase_id") or "").strip()
            en = normalize_text(request.form.get("english") or "")
            om = normalize_text(request.form.get("oromo") or "")
            if not pid_raw.isdigit():
                msg = "Invalid phrase id."
            elif not en or not om:
                msg = "Both English and Oromo are required."
            else:
                pid = int(pid_raw)
                conn = sqlite3.connect(DB_NAME)
                c = conn.cursor()

                c.execute("SELECT 1 FROM phrases WHERE id=? AND status='approved'", (pid,))
                if not c.fetchone():
                    msg = "Phrase not found (or not approved)."
                else:
                    c.execute("""
                        SELECT 1 FROM phrases
                        WHERE id != ? AND (english=? OR oromo=?)
                        LIMIT 1
                    """, (pid, en, om))
                    if c.fetchone():
                        msg = "Duplicate conflict: another phrase already uses that English or Oromo."
                    else:
                        c.execute("UPDATE phrases SET english=?, oromo=? WHERE id=?", (en, om, pid))
                        conn.commit()
                        msg = "Phrase updated."
                conn.close()

        elif action == "delete_phrase":
            pid_raw = (request.form.get("phrase_id") or "").strip()
            if not pid_raw.isdigit():
                msg = "Invalid phrase id."
            else:
                pid = int(pid_raw)

                delete_audio_for_entry("phrase", pid)

                conn = sqlite3.connect(DB_NAME)
                c = conn.cursor()
                c.execute("DELETE FROM phrases WHERE id=? AND status='approved'", (pid,))
                conn.commit()
                conn.close()
                msg = "Phrase deleted permanently."

        else:
            msg = "Unknown action."

    # GET (or after POST): load data for admin_manage.html
    word_q = (request.args.get("word_q") or "").strip()
    phrase_q = (request.args.get("phrase_q") or "").strip()

    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()

    c.execute("SELECT id, email FROM admin ORDER BY id ASC")
    admins = c.fetchall()

    # Approved words (search)
    if word_q:
        q = "%" + normalize_text(word_q) + "%"
        c.execute("""
            SELECT id, english, oromo
            FROM words
            WHERE status='approved' AND (english LIKE ? OR oromo LIKE ?)
            ORDER BY english ASC
            LIMIT 200
        """, (q, q))
    else:
        c.execute("""
            SELECT id, english, oromo
            FROM words
            WHERE status='approved'
            ORDER BY id DESC
            LIMIT 50
        """)
    approved_words = c.fetchall()

    # Approved phrases (search)
    if phrase_q:
        q = "%" + normalize_text(phrase_q) + "%"
        c.execute("""
            SELECT id, english, oromo
            FROM phrases
            WHERE status='approved' AND (english LIKE ? OR oromo LIKE ?)
            ORDER BY id DESC
            LIMIT 200
        """, (q, q))
    else:
        c.execute("""
            SELECT id, english, oromo
            FROM phrases
            WHERE status='approved'
            ORDER BY id DESC
            LIMIT 50
        """)
    approved_phrases = c.fetchall()

    conn.close()

    return render_template(
        "admin_manage.html",
        msg=msg,
        admins=admins,
        approved_words=approved_words,
        approved_phrases=approved_phrases,
        word_q=word_q,
        phrase_q=phrase_q
    )


# ------------------ CHANGE PASSWORD (MY ACCOUNT) ------------------

@app.route("/admin/change_password", methods=["GET", "POST"])
def admin_change_password():
    if not require_admin():
        return redirect("/admin")

    msg = None

    if request.method == "POST":
        current_pw = request.form.get("current_password") or ""
        new_pw = request.form.get("new_password") or ""
        new_pw2 = request.form.get("new_password2") or ""

        if not new_pw or len(new_pw) < 6:
            msg = "New password must be at least 6 characters."
        elif new_pw != new_pw2:
            msg = "New passwords do not match."
        else:
            conn = sqlite3.connect(DB_NAME)
            c = conn.cursor()
            c.execute("SELECT password FROM admin WHERE id=?", (_admin_id(),))
            row = c.fetchone()
            if not row or not check_password_hash(row[0], current_pw):
                msg = "Current password is incorrect."
            else:
                c.execute("UPDATE admin SET password=? WHERE id=?", (generate_password_hash(new_pw), _admin_id()))
                conn.commit()
                msg = "Password updated."
            conn.close()

    # If you already have a change_password template, it will be used.
    # If not, you can reuse admin_manage.html message area and add a small form there,
    # but since you said you already have templates, we keep this as-is.
    return render_template("admin_change_password.html", msg=msg)


# ------------------ ADMIN IMPORT (ENGLISH-ONLY -> GOOGLE -> OROMO) ------------------

def _words_exist(conn, english_word: str) -> bool:
    c = conn.cursor()
    c.execute("SELECT 1 FROM words WHERE english=? OR oromo=? LIMIT 1", (english_word, english_word))
    return c.fetchone() is not None

@app.route("/admin/import", methods=["GET", "POST"])
def admin_import():
    if not require_admin():
        return redirect("/admin")

    msg = None

    if request.method == "POST":
        words = []

        if request.is_json:
            data = request.get_json(silent=True) or {}
            incoming = data.get("words", [])
            if not isinstance(incoming, list):
                return jsonify({"error": "JSON must include 'words' as a list"}), 400
            words = [normalize_text(x) for x in incoming if str(x).strip()]
        else:
            f = request.files.get("file") or request.files.get("txt_file")
            if not f or not f.filename:
                msg = "Please upload a TXT / CSV / XLSX file (English-only list)."
                return render_template("admin_import.html", msg=msg)

            filename = (f.filename or "").lower().strip()
            data = f.read()

            try:
                if filename.endswith(".txt"):
                    words = parse_txt_english(data)
                elif filename.endswith(".csv"):
                    words = parse_csv_english(data)
                elif filename.endswith(".xlsx"):
                    words = parse_xlsx_english(data)
                else:
                    msg = "Only .txt, .csv, .xlsx files are supported."
                    return render_template("admin_import.html", msg=msg)
            except Exception as e:
                app.logger.exception(f"admin_import parse error: {repr(e)}")
                msg = "Could not read the file. Please check its format."
                return render_template("admin_import.html", msg=msg)

        words = [w for w in words if w]
        words = dedup_preserve_order(words)

        if not words:
            if request.is_json:
                return jsonify({"error": "No words provided"}), 400
            msg = "No English words found."
            return render_template("admin_import.html", msg=msg)

        if len(words) > IMPORT_MAX_WORDS:
            words = words[:IMPORT_MAX_WORDS]
            msg = f"Only first {IMPORT_MAX_WORDS} words processed (fixed limit)."

        total_chars = sum(len(x) for x in words)

        inserted = 0
        skipped = 0
        failed = 0
        google_calls = 0

        conn = sqlite3.connect(DB_NAME)
        c = conn.cursor()

        batches = []
        for i in range(0, len(words), IMPORT_BATCH_SIZE):
            batches.append(words[i:i + IMPORT_BATCH_SIZE])
            if len(batches) >= IMPORT_MAX_CALLS:
                break

        for batch in batches:
            to_translate = []
            for en in batch:
                if _words_exist(conn, en):
                    skipped += 1
                else:
                    to_translate.append(en)

            if not to_translate:
                continue

            google_calls += 1
            oms = google_translate_batch_v2(to_translate, target="om", source="en")

            if not oms or len(oms) != len(to_translate):
                failed += len(to_translate)
                continue

            for en, om in zip(to_translate, oms):
                if not om:
                    failed += 1
                    continue

                c.execute("SELECT 1 FROM words WHERE english=? OR oromo=? LIMIT 1", (en, om))
                if c.fetchone():
                    skipped += 1
                    continue

                c.execute("INSERT INTO words (english, oromo, status) VALUES (?, ?, 'pending')", (en, om))
                inserted += 1

        conn.commit()
        conn.close()

        msg2 = (
            f"One-click import done. Imported: {inserted} | Skipped: {skipped} | Failed: {failed} | "
            f"Google calls used: {google_calls}/{IMPORT_MAX_CALLS}. "
            f"Processed {len(words)} words ({total_chars} chars). Approve in Dashboard."
        )
        msg = (msg + " " + msg2).strip() if msg else msg2

        if request.is_json:
            return jsonify({
                "processed": len(words),
                "total_chars": total_chars,
                "imported": inserted,
                "skipped": skipped,
                "failed": failed,
                "google_calls_used": google_calls,
                "google_calls_max": IMPORT_MAX_CALLS,
                "batch_size": IMPORT_BATCH_SIZE,
                "max_words": IMPORT_MAX_WORDS,
                "message": msg
            })

    return render_template("admin_import.html", msg=msg)


# ------------------ APPROVE / REJECT WORDS ------------------

@app.route("/approve/<int:word_id>")
def approve(word_id):
    if not require_admin():
        return redirect("/admin")

    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("UPDATE words SET status='approved' WHERE id=?", (word_id,))
    conn.commit()
    conn.close()
    return redirect("/dashboard")

@app.route("/reject/<int:word_id>")
def reject(word_id):
    if not require_admin():
        return redirect("/admin")

    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("DELETE FROM words WHERE id=? AND status='pending'", (word_id,))
    conn.commit()
    conn.close()
    return redirect("/dashboard")


# ------------------ APPROVE / REJECT PHRASES ------------------

@app.route("/approve_phrase/<int:phrase_id>")
def approve_phrase(phrase_id):
    if not require_admin():
        return redirect("/admin")

    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("UPDATE phrases SET status='approved' WHERE id=?", (phrase_id,))
    conn.commit()
    conn.close()
    return redirect("/dashboard")

@app.route("/reject_phrase/<int:phrase_id>")
def reject_phrase(phrase_id):
    if not require_admin():
        return redirect("/admin")

    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("DELETE FROM phrases WHERE id=? AND status='pending'", (phrase_id,))
    conn.commit()
    conn.close()
    return redirect("/dashboard")


# ------------------ APPROVE / REJECT AUDIO ------------------

@app.route("/approve_audio/<int:audio_id>")
def approve_audio(audio_id):
    if not require_admin():
        return redirect("/admin")

    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("UPDATE audio SET status='approved' WHERE id=?", (audio_id,))
    conn.commit()
    conn.close()
    return redirect("/dashboard")

@app.route("/reject_audio/<int:audio_id>")
def reject_audio(audio_id):
    if not require_admin():
        return redirect("/admin")

    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    # also delete file best-effort
    c.execute("SELECT file_path FROM audio WHERE id=? AND status='pending'", (audio_id,))
    row = c.fetchone()
    c.execute("DELETE FROM audio WHERE id=? AND status='pending'", (audio_id,))
    conn.commit()
    conn.close()

    if row and row[0]:
        abs_path = _audio_abs_path(row[0])
        if abs_path and os.path.isfile(abs_path):
            try:
                os.remove(abs_path)
            except Exception:
                app.logger.exception(f"Could not delete pending audio file: {abs_path}")

    return redirect("/dashboard")


# ------------------ LOGOUT ------------------

@app.route("/logout")
def logout():
    session.pop("admin", None)
    return redirect("/")


# ------------------ CREATE FIRST ADMIN (RUN ONCE) ------------------

@app.route("/create_admin")
def create_admin():
    if os.environ.get("ENABLE_CREATE_ADMIN") != "1":
        return "Disabled."

    email = "jewargure1@gmail.com"
    password = generate_password_hash("admin123")

    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()

    c.execute("SELECT 1 FROM admin WHERE email=?", (email,))
    if not c.fetchone():
        c.execute("INSERT INTO admin (email, password) VALUES (?, ?)", (email, password))
        conn.commit()

    conn.close()
    return "Admin created (or already exists). You can now login."

@app.route("/admin/reset_password", methods=["GET", "POST"])
def admin_reset_password():
    if os.environ.get("ENABLE_ADMIN_RESET") != "1":
        return "Disabled", 403

    token = request.args.get("token", "")
    if token != os.environ.get("ADMIN_RESET_TOKEN", ""):
        return "Forbidden", 403

    if request.method == "POST":
        email = (request.form.get("email") or "").strip().lower()
        new_pw = request.form.get("new_password") or ""
        if not email or len(new_pw) < 6:
            return "Email required and password must be 6+ chars", 400

        conn = sqlite3.connect(DB_NAME)
        c = conn.cursor()
        c.execute("SELECT id FROM admin WHERE email=?", (email,))
        row = c.fetchone()
        if not row:
            conn.close()
            return "Admin email not found in this DB", 404

        c.execute("UPDATE admin SET password=? WHERE email=?",
                  (generate_password_hash(new_pw), email))
        conn.commit()
        conn.close()
        return "Password reset OK. Go to /admin and login."

    return """
    <form method="POST">
      <input name="email" placeholder="admin email" required><br><br>
      <input name="new_password" placeholder="new password (6+)" required><br><br>
      <button type="submit">Reset</button>
    </form>
    """



# ------------------ RUN ------------------

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)



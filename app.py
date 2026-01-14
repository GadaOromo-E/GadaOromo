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
- Public submission (words + phrases) -> BOTH languages required
- Community file submission (CSV/XLSX) -> BOTH languages required (NO Google calls)
- Community audio upload + admin approve/reject

UPDATED (Fix request):
✅ Removed GitHub env var dependency (WORDLIST_URL removed)
✅ Removed broken one-click GitHub import logic (/admin/import_github removed)
✅ Admin bulk import now supports:
   - TXT / CSV / XLSX uploads
   - BOTH languages required for every row (English + Oromo)
   - NO Google Translate calls
"""

import os
import re
import sqlite3
import logging
from uuid import uuid4
from difflib import get_close_matches

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

DB_NAME = "gadaoromo.db"


# ------------------ UPLOAD CONFIG (AUDIO) ------------------

UPLOAD_FOLDER = os.path.join("static", "uploads")
ALLOWED_AUDIO = {"mp3", "wav", "m4a"}
MAX_AUDIO_MB = 15

os.makedirs(UPLOAD_FOLDER, exist_ok=True)
app.config["MAX_CONTENT_LENGTH"] = MAX_AUDIO_MB * 1024 * 1024


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

    # dedup by english (keep first)
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

        # Skip header-like first row
        if idx == 0 and str(a).strip().lower() in ("english", "en") and str(b).strip().lower() in ("oromo", "om"):
            continue

        en = normalize_text(str(a))
        om = normalize_text(str(b))
        if en or om:
            out.append((en, om))

    # dedup by english (keep first)
    seen = set()
    final = []
    for en, om in out:
        if en and en not in seen:
            seen.add(en)
            final.append((en, om))
    return final


def parse_txt_pairs(file_bytes: bytes):
    """
    TXT format (Admin import):
    - Each line must contain BOTH English and Oromo.
    Accepted separators per line:
      - TAB
      - semicolon ;
      - comma ,
    Example:
      hello<TAB>akkam
      water;bishaan
      good morning,akkam bulte
    """
    text = file_bytes.decode("utf-8", errors="replace")
    pairs = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue

        # Try separators in order
        sep = None
        for s in ("\t", ";", ","):
            if s in line:
                sep = s
                break

        if not sep:
            # English-only line not allowed
            pairs.append((normalize_text(line), ""))
            continue

        left, right = line.split(sep, 1)
        en = normalize_text(left)
        om = normalize_text(right)
        pairs.append((en, om))

    # dedup by english
    seen = set()
    final = []
    for en, om in pairs:
        if en and en not in seen:
            seen.add(en)
            final.append((en, om))
    return final


# ------------------ ADMIN HELPER ------------------

def require_admin() -> bool:
    return "admin" in session


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

    c.execute("SELECT english, oromo FROM words WHERE status='approved' ORDER BY english ASC")
    all_words = c.fetchall()
    conn.close()

    trending = get_trending(limit=15)

    return render_template(
        "index.html",
        result=result,
        result_id=result_id,
        audio=audio,
        words=all_words,
        suggestions=suggestions,
        trending=trending
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

    return render_template(
        "translate.html",
        result=result,
        text=text,
        direction=direction,
        suggestions=suggestions,
        trending=trending,
        matched=matched,
        audio=audio
    )


# ------------------ PUBLIC SUBMISSION (WORDS) ------------------

@app.route("/submit", methods=["GET", "POST"])
def submit():
    if request.method == "POST":
        english = normalize_text(request.form.get("english", ""))
        oromo = normalize_text(request.form.get("oromo", ""))

        # Community policy: BOTH required
        if not english or not oromo:
            return "Please provide both English and Oromo. <a href='/submit'>Try again</a>"

        conn = sqlite3.connect(DB_NAME)
        c = conn.cursor()

        c.execute("SELECT 1 FROM words WHERE english=? OR oromo=?", (english, oromo))
        if c.fetchone():
            conn.close()
            return "This word already exists (or is pending). <a href='/submit'>Try another</a>"

        c.execute("INSERT INTO words (english, oromo, status) VALUES (?, ?, 'pending')", (english, oromo))
        conn.commit()
        conn.close()

        return "Thank you! Your word is waiting for admin approval. <br><a href='/'>Go back</a>"

    return render_template("submit.html")


# ------------------ PUBLIC SUBMISSION (PHRASES) + FILE UPLOAD ------------------

@app.route("/submit_phrase", methods=["GET", "POST"])
def submit_phrase():
    """
    Community policy:
    - manual submit requires BOTH english + oromo
    - file submit requires BOTH english + oromo for EVERY row
    - NO Google calls here
    Accepts:
    - manual form: fields english, oromo
    - file form: upload CSV/XLSX with both columns
    """
    msg = None

    if request.method == "POST":
        mode = (request.form.get("mode") or "").strip().lower()

        # If file exists OR mode=file -> treat as file upload
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

            # Enforce: BOTH columns required in EVERY row
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

        # Otherwise manual submission
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


# ------------------ COMMUNITY FILE SUBMISSION (WORDS CSV/XLSX ONLY) ------------------

@app.route("/submit_file", methods=["GET", "POST"])
def submit_file():
    """
    Community can submit a translated WORD file for approval.
    Policy:
    - Only CSV or XLSX
    - MUST contain BOTH English + Oromo for every row
    - NO Google translate calls here
    """
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
            return "Allowed audio: mp3, wav, m4a", 400

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

        return "Thanks! Audio submitted for admin approval. <br><a href='/'>Home</a>"

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

    conn.close()

    return render_template(
        "admin_dashboard.html",
        pending=pending_words,
        pending_phrases=pending_phrases,
        pending_audio=pending_audio
    )


# ------------------ ADMIN IMPORT (UPLOAD TXT/CSV/XLSX, BOTH LANG REQUIRED, NO GOOGLE) ------------------

def _word_exists_any(conn, english_word: str, oromo_word: str) -> bool:
    c = conn.cursor()
    c.execute("SELECT 1 FROM words WHERE english=? OR oromo=? OR english=? OR oromo=? LIMIT 1",
              (english_word, english_word, oromo_word, oromo_word))
    return c.fetchone() is not None


@app.route("/admin/import", methods=["GET", "POST"])
def admin_import():
    """
    Admin import supports:
    - Upload TXT / CSV / XLSX with BOTH languages required (English + Oromo)
    - JSON POST also supported:
        {"pairs":[{"english":"..","oromo":".."}, ...]}
        OR {"rows":[["english","oromo"], ...]}

    Notes:
    - No GitHub import
    - No Google Translate calls
    - Saves imported rows as 'pending' for admin approval.
    """
    if not require_admin():
        return redirect("/admin")

    msg = None

    if request.method == "POST":
        pairs = []

        # -------- JSON mode --------
        if request.is_json:
            data = request.get_json(silent=True) or {}

            if isinstance(data.get("pairs"), list):
                for item in data["pairs"]:
                    if not isinstance(item, dict):
                        continue
                    en = normalize_text(item.get("english", ""))
                    om = normalize_text(item.get("oromo", ""))
                    if en or om:
                        pairs.append((en, om))

            elif isinstance(data.get("rows"), list):
                for row in data["rows"]:
                    if not isinstance(row, (list, tuple)) or len(row) < 2:
                        continue
                    en = normalize_text(str(row[0]))
                    om = normalize_text(str(row[1]))
                    if en or om:
                        pairs.append((en, om))

            # Backward compatibility (but now rejected because English-only is not allowed)
            elif isinstance(data.get("words"), list):
                return jsonify({
                    "error": "English-only import is not allowed anymore. Please send pairs (english+oromo).",
                    "expected": {"pairs": [{"english": "...", "oromo": "..."}]}
                }), 400

            else:
                return jsonify({
                    "error": "Invalid JSON body.",
                    "expected": {"pairs": [{"english": "...", "oromo": "..."}]}
                }), 400

        # -------- FILE mode --------
        else:
            f = request.files.get("file") or request.files.get("txt_file")
            if not f or not f.filename:
                msg = "Please upload a TXT / CSV / XLSX file."
                return render_template("admin_import.html", msg=msg)

            filename = (f.filename or "").lower().strip()
            data = f.read()

            try:
                if filename.endswith(".txt"):
                    pairs = parse_txt_pairs(data)
                elif filename.endswith(".csv"):
                    pairs = parse_csv_pairs(data)
                elif filename.endswith(".xlsx"):
                    pairs = parse_xlsx_pairs(data)
                else:
                    msg = "Only .txt, .csv, .xlsx files are supported."
                    return render_template("admin_import.html", msg=msg)
            except Exception as e:
                app.logger.exception(f"admin_import parse error: {repr(e)}")
                msg = "Could not read the file. Please check its format."
                return render_template("admin_import.html", msg=msg)

        # cleanup
        pairs = [(en, om) for en, om in pairs if en or om]

        if not pairs:
            if request.is_json:
                return jsonify({"error": "No rows found."}), 400
            msg = "No rows found."
            return render_template("admin_import.html", msg=msg)

        # Enforce BOTH required
        invalid_rows = [(en, om) for en, om in pairs if not en or not om]
        if invalid_rows:
            bad_count = len(invalid_rows)
            if request.is_json:
                return jsonify({
                    "error": "Rejected: every row must have BOTH English and Oromo.",
                    "invalid_rows_count": bad_count,
                    "hint": "For TXT use: english<TAB>oromo (or english;oromo). For CSV headers: english,oromo. For XLSX: col A English, col B Oromo."
                }), 400
            msg = f"Rejected: every row must include BOTH English and Oromo. Invalid rows: {bad_count}"
            return render_template("admin_import.html", msg=msg)

        inserted = 0
        skipped = 0

        conn = sqlite3.connect(DB_NAME)
        c = conn.cursor()

        for en, om in pairs:
            if _word_exists_any(conn, en, om):
                skipped += 1
                continue
            c.execute("INSERT INTO words (english, oromo, status) VALUES (?, ?, 'pending')", (en, om))
            inserted += 1

        conn.commit()
        conn.close()

        msg = f"Import completed. Added: {inserted} | Skipped duplicates: {skipped}. Now approve in Dashboard."

        if request.is_json:
            return jsonify({
                "rows_received": len(pairs),
                "inserted": inserted,
                "skipped": skipped,
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
    c.execute("DELETE FROM audio WHERE id=? AND status='pending'", (audio_id,))
    conn.commit()
    conn.close()
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


# ------------------ RUN ------------------

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)

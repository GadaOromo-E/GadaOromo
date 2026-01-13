# -*- coding: utf-8 -*-
"""
Created on Sun Jan 11 16:32:35 2026

@author: ademo
"""
from flask import Flask, render_template, request, redirect, session
import sqlite3
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
import os
import re
from difflib import get_close_matches
from uuid import uuid4
import requests

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "dev_only_change_me")

DB_NAME = "gadaoromo.db"

# ------------------ UPLOAD CONFIG (AUDIO) ------------------

UPLOAD_FOLDER = os.path.join("static", "uploads")
ALLOWED_AUDIO = {"mp3", "wav", "m4a"}
MAX_AUDIO_MB = 15  # adjust if needed

os.makedirs(UPLOAD_FOLDER, exist_ok=True)
app.config["MAX_CONTENT_LENGTH"] = MAX_AUDIO_MB * 1024 * 1024

# ------------------ STOPWORDS (START SMALL, EXPAND LATER) ------------------

OROMO_STOP = {"fi", "kan", "inni", "isaan", "ani", "ati", "nu", "keessa", "irratti"}
EN_STOP = {"the", "is", "are", "to", "and", "of", "in", "on", "a", "an", "for", "with", "it", "this"}

# ------------------ TEXT NORMALIZATION ------------------

def normalize_text(text: str) -> str:
    t = (text or "").lower().strip()
    t = re.sub(r"[^\w\s]", " ", t)      # punctuation clean
    t = re.sub(r"\s+", " ", t).strip()  # collapse spaces
    return t

def normalize_tokens(text: str):
    t = normalize_text(text)
    return t.split() if t else []

# ------------------ ADMIN HELPER ------------------

def require_admin() -> bool:
    return "admin" in session

# ------------------ GOOGLE TRANSLATE (CLOUD v2) ------------------
# Uses env var: GOOGLE_TRANSLATE_API_KEY

def google_translate_v2(text: str, target: str, source: str = "en") -> str:
    api_key = os.environ.get("GOOGLE_TRANSLATE_API_KEY", "").strip()
    if not api_key:
        print("GOOGLE_TRANSLATE_API_KEY is missing")
        return ""

    url = "https://translation.googleapis.com/language/translate/v2"
    payload = {
        "q": text,
        "source": source,
        "target": target,   # Oromo should be "om"
        "format": "text",
        "key": api_key
    }

    try:
        r = requests.post(url, data=payload, timeout=20)
        if r.status_code != 200:
            print("Google Translate API error:", r.status_code, r.text)
            return ""

        data = r.json()
        out = data["data"]["translations"][0]["translatedText"]
        return normalize_text(out)

    except Exception as e:
        print("Google Translate exception:", repr(e))
        return ""


# ------------------ AUDIO HELPERS ------------------

def allowed_audio(filename: str) -> bool:
    if not filename or "." not in filename:
        return False
    ext = filename.rsplit(".", 1)[1].lower()
    return ext in ALLOWED_AUDIO

def get_approved_audio(entry_type: str, entry_id: int) -> dict:
    """
    Returns {'oromo': 'uploads/x.mp3', 'english': 'uploads/y.mp3'} for approved audio.
    entry_type: 'word' or 'phrase'
    """
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

    # Words table
    c.execute("""
        CREATE TABLE IF NOT EXISTS words (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            english TEXT,
            oromo TEXT,
            status TEXT
        )
    """)

    # Phrases table
    c.execute("""
        CREATE TABLE IF NOT EXISTS phrases (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            english TEXT,
            oromo TEXT,
            status TEXT
        )
    """)

    # Admin table
    c.execute("""
        CREATE TABLE IF NOT EXISTS admin (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT,
            password TEXT
        )
    """)

    # Analytics: raw logs (optional but useful)
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

    # Analytics: aggregated counts (fast trending)
    c.execute("""
        CREATE TABLE IF NOT EXISTS search_counts (
            query TEXT PRIMARY KEY,
            total_count INTEGER DEFAULT 0,
            today_count INTEGER DEFAULT 0,
            week_count INTEGER DEFAULT 0,
            last_searched_at DATETIME
        )
    """)

    # Community audio recordings (admin approved)
    c.execute("""
        CREATE TABLE IF NOT EXISTS audio (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            entry_type TEXT,      -- 'word' or 'phrase'
            entry_id INTEGER,     -- id from words/phrases table
            lang TEXT,            -- 'oromo' or 'english'
            file_path TEXT,       -- 'uploads/abc.mp3'
            status TEXT           -- 'pending' or 'approved'
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

# ------------------ SUGGESTIONS (“DID YOU MEAN…”) ------------------

def suggest_terms(term: str, direction: str, limit: int = 8):
    t = normalize_text(term)
    if not t:
        return {"closest": [], "prefix": [], "partial": []}

    col = "oromo" if direction == "om_en" else "english"

    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()

    # Prefix matches
    c.execute(f"""
        SELECT {col} FROM words
        WHERE status='approved' AND {col} LIKE ?
        LIMIT ?
    """, (t + "%", limit))
    prefix = [r[0] for r in c.fetchall()]

    # Partial matches
    c.execute(f"""
        SELECT {col} FROM words
        WHERE status='approved' AND {col} LIKE ?
        LIMIT ?
    """, ("%" + t + "%", limit))
    partial = [r[0] for r in c.fetchall()]

    # Fuzzy candidates (cap to avoid huge scan)
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

# ------------------ AUTO LANGUAGE DETECT (IMPROVED) ------------------

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

    # Phrase exact match bonus
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

# ------------------ TRANSLATION LOGIC (PHRASES FIRST, THEN WORDS) ------------------

def translate_text(text: str, direction: str = "om_en"):
    """
    Returns: (translated_text, is_exact, is_phrase)
    is_exact: 1 when exact phrase/word found, else 0
    is_phrase: 1 when exact phrase matched, else 0
    """
    t = normalize_text(text)
    if not t:
        return "", 0, 0

    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()

    # 1) Phrase exact match
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

    # 2) Word exact match (only if input is single token)
    tokens = t.split()
    if len(tokens) == 1:
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

    # 3) Word-by-word fallback
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
    matched = None  # {'type': 'word'|'phrase', 'id': int}

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

# ------------------ PUBLIC SUBMISSION (PHRASES) ------------------

@app.route("/submit_phrase", methods=["GET", "POST"])
def submit_phrase():
    if request.method == "POST":
        english = normalize_text(request.form.get("english", ""))
        oromo = normalize_text(request.form.get("oromo", ""))

        if not english or not oromo:
            return "Please provide both English and Oromo phrase. <a href='/submit_phrase'>Try again</a>"

        conn = sqlite3.connect(DB_NAME)
        c = conn.cursor()

        c.execute("SELECT 1 FROM phrases WHERE english=? OR oromo=?", (english, oromo))
        if c.fetchone():
            conn.close()
            return "This phrase already exists (or is pending). <a href='/submit_phrase'>Try another</a>"

        c.execute("INSERT INTO phrases (english, oromo, status) VALUES (?, ?, 'pending')", (english, oromo))
        conn.commit()
        conn.close()

        return "Thank you! Your phrase is waiting for admin approval. <br><a href='/'>Go back</a>"

    return render_template("submit_phrase.html")

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
        admin = c.fetchone()
        conn.close()

        if admin and check_password_hash(admin[1], password):
            session["admin"] = admin[0]
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

# ------------------ ADMIN IMPORT (GOOGLE CLOUD TRANSLATE) ------------------

@app.route("/admin/import", methods=["GET", "POST"])
def admin_import():
    if not require_admin():
        return redirect("/admin")

    msg = None

    if request.method == "POST":
        raw = request.form.get("words", "")
        lines = [normalize_text(x) for x in raw.splitlines()]
        lines = [x for x in lines if x]

        if not lines:
            msg = "No words provided."
            return render_template("admin_import.html", msg=msg)

        # Safety limit to control cost
        MAX_LINES = 200
        if len(lines) > MAX_LINES:
            lines = lines[:MAX_LINES]
            msg = f"Only first {MAX_LINES} lines were processed (cost control)."

        inserted = 0
        skipped = 0
        failed = 0

        conn = sqlite3.connect(DB_NAME)
        c = conn.cursor()

        for en in lines:
            # skip if exists already (approved or pending)
            c.execute("SELECT 1 FROM words WHERE english=? OR oromo=?", (en, en))
            if c.fetchone():
                skipped += 1
                continue

            om = google_translate_v2(en, target="om", source="en")
            if not om:
                failed += 1
                continue

            # avoid duplicates after translation
            c.execute("SELECT 1 FROM words WHERE english=? OR oromo=?", (en, om))
            if c.fetchone():
                skipped += 1
                continue

            c.execute(
                "INSERT INTO words (english, oromo, status) VALUES (?, ?, 'pending')",
                (en, om)
            )
            inserted += 1

        conn.commit()
        conn.close()

        msg2 = f"Imported: {inserted} | Skipped: {skipped} | Failed: {failed}. Approve in Dashboard."
        msg = (msg + " " + msg2).strip() if msg else msg2

    return render_template("admin_import.html", msg=msg)

# ------------------ ADMIN MANAGEMENT ------------------

@app.route("/admin/manage", methods=["GET", "POST"])
def admin_manage():
    if not require_admin():
        return redirect("/admin")

    msg = None

    if request.method == "POST":
        action = request.form.get("action", "")

        if action == "add_admin":
            email = (request.form.get("email") or "").strip().lower()
            password = request.form.get("password") or ""

            if not email or not password:
                msg = "Please provide email and password."
            else:
                pw_hash = generate_password_hash(password)
                conn = sqlite3.connect(DB_NAME)
                c = conn.cursor()
                c.execute("SELECT 1 FROM admin WHERE email=?", (email,))
                if c.fetchone():
                    msg = "Admin already exists with this email."
                else:
                    c.execute("INSERT INTO admin (email, password) VALUES (?, ?)", (email, pw_hash))
                    conn.commit()
                    msg = "New admin added successfully."
                conn.close()

        elif action == "delete_admin":
            admin_id = int(request.form.get("admin_id") or "0")
            current_id = int(session.get("admin"))

            if admin_id == current_id:
                msg = "You cannot delete your own admin account."
            else:
                conn = sqlite3.connect(DB_NAME)
                c = conn.cursor()
                c.execute("DELETE FROM admin WHERE id=?", (admin_id,))
                conn.commit()
                conn.close()
                msg = "Admin deleted."

    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("SELECT id, email FROM admin ORDER BY id ASC")
    admins = c.fetchall()
    conn.close()

    return render_template("admin_manage.html", admins=admins, msg=msg)

@app.route("/admin/change_password", methods=["GET", "POST"])
def admin_change_password():
    if not require_admin():
        return redirect("/admin")

    msg = None

    if request.method == "POST":
        current_pw = request.form.get("current_password") or ""
        new_pw = request.form.get("new_password") or ""
        confirm_pw = request.form.get("confirm_password") or ""

        if not current_pw or not new_pw or not confirm_pw:
            msg = "Please fill in all fields."
        elif new_pw != confirm_pw:
            msg = "New passwords do not match."
        elif len(new_pw) < 6:
            msg = "Password must be at least 6 characters."
        else:
            admin_id = session["admin"]
            conn = sqlite3.connect(DB_NAME)
            c = conn.cursor()
            c.execute("SELECT password FROM admin WHERE id=?", (admin_id,))
            row = c.fetchone()

            if not row or not check_password_hash(row[0], current_pw):
                msg = "Current password is incorrect."
                conn.close()
            else:
                c.execute("UPDATE admin SET password=? WHERE id=?", (generate_password_hash(new_pw), admin_id))
                conn.commit()
                conn.close()
                msg = "Password changed successfully."

    return render_template("admin_change_password.html", msg=msg)

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
# IMPORTANT: Protect this route with an environment variable.
# Set: ENABLE_CREATE_ADMIN=1 only temporarily.

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
# -*- coding: utf-8 -*-
"""
Created on Sun Jan 11 16:32:35 2026

@author: ademo
"""
"""
Gada Oromo Dictionary - Flask + SQLite + PWA-ready

✅ Includes:
- Dictionary search + translate pages
- Admin login + dashboard + approve/reject
- Public submission: words + phrases (manual + CSV/XLSX)
- Legacy /submit_file kept
- Admin bulk import (TXT/CSV/XLSX English-only) -> Google Translate -> pending
- Community audio upload + admin approve/reject
- In-page mic recording posts to: POST /api/submit-audio
- /learn, /support
- PWA support:
    - /manifest.webmanifest
    - /service-worker.js (root scope)
    - /offline
- SEO / Google:
    - /robots.txt
    - /sitemap.xml
    - ProxyFix for Render (correct https URLs)
    - google verification file route
"""

import os
import re
import sqlite3
import logging
import csv
from uuid import uuid4
from difflib import get_close_matches
from io import StringIO, BytesIO
from datetime import datetime

import requests
from flask import (
    Flask, render_template, request, redirect, session,
    jsonify, send_from_directory, abort, make_response
)
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from werkzeug.middleware.proxy_fix import ProxyFix
from openpyxl import load_workbook


# ------------------ APP SETUP ------------------

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "dev_only_change_me")

# ✅ IMPORTANT for Render / reverse proxy: makes Flask understand HTTPS + correct host
# (needed for correct absolute URLs, sitemap, redirects, etc.)
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_port=1)

logging.basicConfig(level=logging.INFO)
app.logger.setLevel(logging.INFO)

BASE_DIR = os.path.abspath(os.path.dirname(__file__))
DEFAULT_DB = os.path.join(BASE_DIR, "gadaoromo.db")

DB_NAME = os.environ.get("DB_PATH", "").strip() or DEFAULT_DB
app.logger.info(f"✅ Using DB_NAME={DB_NAME}")

APP_NAME = os.environ.get("APP_NAME", "Gadaa Dictionary")


# If you set WEBSITE_URL in Render env vars, we use it for sitemap/canonical.
# If not set, we auto-detect from request.url_root.
WEBSITE_URL = os.environ.get("WEBSITE_URL", "").strip().rstrip("/")
API_URL = os.environ.get("API_URL", "").strip()

SUPPORT_MIN_NOK = int(os.environ.get("SUPPORT_MIN_NOK", "200"))

DONATE_URLS = {
    "custom": os.environ.get("STRIPE_DONATE_CUSTOM_URL", "").strip(),
}


def _safe_url(u: str) -> str:
    if not u:
        return ""
    u = u.strip()
    if u.startswith("https://") or u.startswith("http://"):
        return u
    return ""


DONATE_URLS = {k: _safe_url(v) for k, v in DONATE_URLS.items()}


def _site_base_url() -> str:
    """
    Base URL for sitemap/SEO. Priority:
    1) WEBSITE_URL env var (recommended)
    2) request.url_root (auto from current request; ProxyFix ensures correct https on Render)
    """
    if WEBSITE_URL:
        return WEBSITE_URL.rstrip("/")
    try:
        root = (request.url_root or "").rstrip("/")
        return root
    except Exception:
        return "https://gadaoromo.onrender.com"


@app.context_processor
def inject_globals():
    return dict(
        APP_NAME=APP_NAME,
        SUPPORT_MIN_NOK=SUPPORT_MIN_NOK,
        DONATE_URLS=DONATE_URLS,
        WEBSITE_URL=WEBSITE_URL,
        API_URL=API_URL,
    )


@app.route("/debug-vars")
def debug_vars():
    return f"SUPPORT_MIN_NOK={SUPPORT_MIN_NOK}, donate_url_set={bool(DONATE_URLS.get('custom'))}"


@app.after_request
def add_security_headers(resp):
    resp.headers["X-Content-Type-Options"] = "nosniff"
    resp.headers["X-Frame-Options"] = "SAMEORIGIN"
    # Helpful default cache policy for HTML
    if resp.mimetype == "text/html":
        resp.headers.setdefault("Cache-Control", "no-cache")
    return resp


# ------------------ SEO: ROBOTS + SITEMAP ------------------

@app.route("/robots.txt")
def robots_txt():
    """
    Allow indexing. Also points Google to sitemap.
    """
    base = _site_base_url()
    lines = [
        "User-agent: *",
        "Allow: /",
        "",
        f"Sitemap: {base}/sitemap.xml",
        "",
    ]
    resp = make_response("\n".join(lines))
    resp.headers["Content-Type"] = "text/plain; charset=utf-8"
    resp.headers["Cache-Control"] = "public, max-age=3600"
    return resp


@app.route("/sitemap.xml")
def sitemap_xml():
    """
    Basic sitemap for main pages.
    If later you add word pages, we can expand it.
    """
    base = _site_base_url()
    urls = [
        ("/", "daily", "1.0"),
        ("/translate", "daily", "0.9"),
        ("/learn", "weekly", "0.6"),
        ("/support", "monthly", "0.3"),
        ("/submit", "weekly", "0.5"),
        ("/submit_phrase", "weekly", "0.5"),
    ]

    now = datetime.utcnow().strftime("%Y-%m-%d")

    xml_parts = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">',
    ]
    for path, freq, prio in urls:
        loc = f"{base}{path}"
        xml_parts.append("<url>")
        xml_parts.append(f"<loc>{loc}</loc>")
        xml_parts.append(f"<lastmod>{now}</lastmod>")
        xml_parts.append(f"<changefreq>{freq}</changefreq>")
        xml_parts.append(f"<priority>{prio}</priority>")
        xml_parts.append("</url>")
    xml_parts.append("</urlset>")

    resp = make_response("\n".join(xml_parts))
    resp.headers["Content-Type"] = "application/xml; charset=utf-8"
    resp.headers["Cache-Control"] = "public, max-age=3600"
    return resp


# ------------------ UPLOAD CONFIG (AUDIO) ------------------

IS_RENDER_DISK = os.path.isdir("/var/data")

if IS_RENDER_DISK:
    UPLOAD_FOLDER = "/var/data/uploads"
else:
    UPLOAD_FOLDER = os.path.join(BASE_DIR, "static", "uploads")

os.makedirs(UPLOAD_FOLDER, exist_ok=True)

ALLOWED_AUDIO = {"mp3", "wav", "m4a", "webm", "ogg"}
MAX_AUDIO_MB = int(os.environ.get("MAX_AUDIO_MB", "15"))
app.config["MAX_CONTENT_LENGTH"] = MAX_AUDIO_MB * 1024 * 1024


# ------------------ PWA ROUTES (IMPORTANT) ------------------
# We serve the service worker from ROOT so it can control the whole site.

@app.route("/manifest.webmanifest")
def manifest():
    resp = make_response(
        send_from_directory(os.path.join(BASE_DIR, "static"), "manifest.webmanifest")
    )
    resp.headers["Content-Type"] = "application/manifest+json"
    # OK to cache a bit (manifest rarely changes), but not forever
    resp.headers["Cache-Control"] = "public, max-age=3600"
    return resp


@app.route("/service-worker.js")
def service_worker():
    resp = make_response(send_from_directory(os.path.join(BASE_DIR, "static"), "service-worker.js"))
    resp.headers["Content-Type"] = "application/javascript"
    resp.headers["Service-Worker-Allowed"] = "/"
    # IMPORTANT: SW updates should not be cached
    resp.headers["Cache-Control"] = "no-cache"
    return resp


@app.route("/offline")
def offline():
    return render_template("offline.html")

@app.route("/favicon.ico")
def favicon():
    return send_from_directory(
        os.path.join(app.root_path, "static", "icons"),
        "favicon.ico",
        mimetype="image/vnd.microsoft.icon"
    )



# ------------------ GOOGLE VERIFICATION ------------------
# You verified using HTML file method. Keep this route forever.

@app.route("/googledba38dd4b1b65cfb.html")
def google_verification():
    resp = make_response("google-site-verification: googledba38dd4b1b65cfb.html")
    resp.headers["Content-Type"] = "text/html; charset=utf-8"
    resp.headers["Cache-Control"] = "public, max-age=3600"
    return resp


# ------------------ PUBLIC UPLOADS ROUTE (AUDIO) ------------------
# Works for both Render disk and local static/uploads.

@app.route("/uploads/<path:filename>")
def uploads(filename):
    safe_name = os.path.basename(filename)
    full_path = os.path.join(UPLOAD_FOLDER, safe_name)
    if not os.path.isfile(full_path):
        abort(404)
    return send_from_directory(UPLOAD_FOLDER, safe_name)


# ------------------ ADMIN IMPORT CONFIG ------------------

IMPORT_BATCH_SIZE = 200
IMPORT_MAX_CALLS = 10
IMPORT_MAX_WORDS = IMPORT_BATCH_SIZE * IMPORT_MAX_CALLS  # 2000


# ------------------ STOPWORDS ------------------

OROMO_STOP = {"fi", "kan", "inni", "isaan", "ani", "ati", "nu", "keessa", "irratti"}
EN_STOP = {"the", "is", "are", "to", "and", "of", "in", "on", "a", "an", "for", "with", "it", "this"}


# ------------------ TEXT NORMALIZATION ------------------

def normalize_text(text: str) -> str:
    t = (text or "").strip().lower()

    # Convert curly apostrophes to normal apostrophe
    t = t.replace("’", "'").replace("‘", "'").replace("`", "'")

    # Keep letters/numbers/underscore/space + apostrophe
    t = re.sub(r"[^\w\s']+", " ", t)

    # Clean extra spaces but DO NOT break apostrophe words
    t = re.sub(r"\s+", " ", t).strip()
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
    text = file_bytes.decode("utf-8", errors="replace")
    words = []
    for line in text.splitlines():
        w = normalize_text(line)
        if w:
            words.append(w)
    return dedup_preserve_order(words)


def parse_csv_english(file_bytes: bytes):
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


def _public_audio_url(file_path: str) -> str:
    """
    DB stores file_path like: 'uploads/xyz.webm'
    This returns a usable URL: '/uploads/xyz.webm'
    """
    fp = (file_path or "").replace("\\", "/").strip()
    if not fp:
        return ""
    if fp.startswith("uploads/"):
        return "/" + fp
    if fp.startswith("/uploads/"):
        return fp
    return "/uploads/" + os.path.basename(fp)


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
            out[lang] = _public_audio_url(path)
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
    fp = (file_path or "").replace("\\", "/").strip()
    if not fp:
        return ""
    name = fp.split("/")[-1]
    return os.path.join(UPLOAD_FOLDER, name)


def delete_audio_for_entry(entry_type: str, entry_id: int):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("SELECT id, file_path FROM audio WHERE entry_type=? AND entry_id=?", (entry_type, entry_id))
    rows = c.fetchall()

    c.execute("DELETE FROM audio WHERE entry_type=? AND entry_id=?", (entry_type, entry_id))
    conn.commit()
    conn.close()

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


# ------------------ LEARN ------------------

@app.route("/learn", methods=["GET"])
def learn():
    trending = get_trending(limit=15)
    return render_template("learn.html", trending=trending)


# ------------------ SUPPORT ------------------

@app.route("/support", methods=["GET"])
def support():
    trending = get_trending(limit=10)
    return render_template("support.html", trending=trending)


# ------------------ HOME ------------------

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


# ------------------ TRANSLATE ------------------

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


# ------------------ PUBLIC SUBMISSION (WORDS) ------------------

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
                    msg = "Rejected: Every row must include BOTH English and Oromo."
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


# ------------------ PUBLIC SUBMISSION (PHRASES) ------------------

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
                    msg = "Rejected: Every row must include BOTH English and Oromo."
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


# ------------------ LEGACY: COMMUNITY FILE SUBMISSION ------------------

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
                msg = "Rejected: Every row must include BOTH English and Oromo."
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


# ------------------ API AUDIO SUBMISSION (OROMO ONLY) ------------------

@app.route("/api/submit-audio", methods=["POST"])
def api_submit_audio():
    """
    Receives audio from in-page recorder (MediaRecorder).
    multipart/form-data:
      entry_type: word|phrase
      entry_id: int
      lang: oromo   (ONLY oromo allowed)
      audio: file
    """
    entry_type = (request.form.get("entry_type") or "").strip().lower()
    entry_id_raw = (request.form.get("entry_id") or "").strip()
    lang = (request.form.get("lang") or "oromo").strip().lower()

    # Validate basics
    if entry_type not in ("word", "phrase"):
        return jsonify({"ok": False, "error": "Invalid entry_type"}), 400
    if not entry_id_raw.isdigit():
        return jsonify({"ok": False, "error": "Invalid entry_id"}), 400

    # ✅ Oromo ONLY
    if lang != "oromo":
        return jsonify({"ok": False, "error": "Only Oromo audio is allowed."}), 400

    entry_id = int(entry_id_raw)

    # Validate file
    f = request.files.get("audio")
    if not f or not f.filename:
        return jsonify({"ok": False, "error": "Missing audio file"}), 400

    # Ensure extension exists
    original = secure_filename(f.filename)
    if "." not in original:
        return jsonify({"ok": False, "error": "Audio file must have an extension (webm/mp3/wav/m4a/ogg)."}), 400

    if not allowed_audio(original):
        return jsonify({"ok": False, "error": "Allowed audio: mp3, wav, m4a, webm, ogg"}), 400

    ext = original.rsplit(".", 1)[1].lower()

    # Entry must exist + be approved
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

    # ✅ Prevent duplicate pending/approved submissions (same entry/lang)
    c.execute("""
        SELECT 1 FROM audio
        WHERE entry_type=? AND entry_id=? AND lang=? AND status IN ('pending','approved')
        LIMIT 1
    """, (entry_type, entry_id, lang))
    if c.fetchone():
        conn.close()
        return jsonify({"ok": False, "error": "Audio already submitted (pending or approved)."}), 409

    # Save file
    new_name = f"{entry_type}_{entry_id}_{lang}_{uuid4().hex}.{ext}"
    save_path = os.path.join(UPLOAD_FOLDER, new_name)
    f.save(save_path)

    # Store relative path for static serving (your app expects this)
    rel_path = f"uploads/{new_name}"

    c.execute("""
        INSERT INTO audio (entry_type, entry_id, lang, file_path, status)
        VALUES (?, ?, ?, ?, 'pending')
    """, (entry_type, entry_id, lang, rel_path))
    conn.commit()
    conn.close()

    return jsonify({"ok": True, "message": "Oromo audio submitted for admin approval."})


# ------------------ COMMUNITY AUDIO UPLOAD PAGE (OROMO ONLY) ------------------

@app.route("/upload_audio/<entry_type>/<int:entry_id>/<lang>", methods=["GET", "POST"])
def upload_audio(entry_type, entry_id, lang):
    """
    Manual file upload page.
    ✅ Oromo ONLY (English audio not accepted)
    ✅ Allow unlimited pending submissions
    ✅ Block only if an APPROVED Oromo audio already exists for this entry
    """
    entry_type = (entry_type or "").strip().lower()
    lang = (lang or "").strip().lower()

    if entry_type not in ("word", "phrase"):
        return "Invalid entry type", 400

    # ✅ Oromo ONLY
    if lang != "oromo":
        return "Only Oromo audio is allowed.", 400

    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()

    # ✅ Entry must exist + be approved
    if entry_type == "word":
        c.execute("SELECT id, english, oromo FROM words WHERE id=? AND status='approved'", (entry_id,))
    else:
        c.execute("SELECT id, english, oromo FROM phrases WHERE id=? AND status='approved'", (entry_id,))

    row = c.fetchone()
    if not row:
        conn.close()
        return "Entry not found or not approved.", 404

    # ✅ Block only if APPROVED already exists (pending should NOT block)
    c.execute("""
        SELECT 1 FROM audio
        WHERE entry_type=? AND entry_id=? AND lang=? AND status='approved'
        LIMIT 1
    """, (entry_type, entry_id, lang))

    already_approved = c.fetchone() is not None
    if already_approved:
        conn.close()
        return "Audio already approved for this entry.", 409

    # ✅ POST: upload as PENDING (allow many)
    if request.method == "POST":
        f = request.files.get("audio")
        if not f or not f.filename:
            conn.close()
            return "Please choose an audio file.", 400

        original = secure_filename(f.filename)
        if "." not in original:
            conn.close()
            return "Audio file must have an extension (webm/mp3/wav/m4a/ogg).", 400

        if not allowed_audio(original):
            conn.close()
            return "Allowed audio: mp3, wav, m4a, webm, ogg", 400

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

        return "Thanks! Oromo audio submitted for admin approval."

    # ✅ GET: show page
    conn.close()
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


# ------------------ ADMIN MANAGEMENT ------------------

@app.route("/admin/manage", methods=["GET", "POST"])
def admin_manage():
    if not require_admin():
        return redirect("/admin")

    msg = None

    if request.method == "POST":
        action = (request.form.get("action") or "").strip()

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

                c.execute("SELECT 1 FROM words WHERE id=? AND status='approved'", (wid,))
                if not c.fetchone():
                    msg = "Word not found (or not approved)."
                else:
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
                delete_audio_for_entry("word", wid)

                conn = sqlite3.connect(DB_NAME)
                c = conn.cursor()
                c.execute("DELETE FROM words WHERE id=? AND status='approved'", (wid,))
                conn.commit()
                conn.close()
                msg = "Word deleted permanently."

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

    word_q = (request.args.get("word_q") or "").strip()
    phrase_q = (request.args.get("phrase_q") or "").strip()

    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()

    c.execute("SELECT id, email FROM admin ORDER BY id ASC")
    admins = c.fetchall()

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


# ------------------ CHANGE PASSWORD ------------------

@app.route("/admin/change_password", methods=["GET", "POST"])
def admin_change_password():
    if not require_admin():
        return redirect("/admin")

    msg = None
    admin_id = session.get("admin")

    if request.method == "POST":
        current_pw = (request.form.get("current_password") or "").strip()
        new_pw = (request.form.get("new_password") or "").strip()
        new_pw2 = (request.form.get("new_password2") or "").strip()

        if len(new_pw) < 6:
            msg = "New password must be at least 6 characters."
        elif new_pw != new_pw2:
            msg = "New passwords do not match."
        else:
            conn = sqlite3.connect(DB_NAME)
            c = conn.cursor()
            c.execute("SELECT password FROM admin WHERE id=?", (admin_id,))
            row = c.fetchone()

            if not row or not check_password_hash(row[0], current_pw):
                msg = "Current password is incorrect."
            else:
                c.execute(
                    "UPDATE admin SET password=? WHERE id=?",
                    (generate_password_hash(new_pw), admin_id)
                )
                conn.commit()
                msg = "Password updated."
            conn.close()

    return render_template("admin_change_password.html", msg=msg)


# ------------------ ADMIN IMPORT (ENGLISH-ONLY -> GOOGLE) ------------------

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


# ------------------ RUN ------------------

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)

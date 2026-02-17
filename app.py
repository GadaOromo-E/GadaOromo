# -*- coding: utf-8 -*-
"""
Created on Sun Jan 11 16:32:35 2026
@author: ademo

Gadaa Dictionary - Flask + SQLite + PWA-ready

Includes:
- Dictionary search + translate pages
- Admin login + dashboard + approve/reject
- Public submission: words + phrases (manual + CSV/XLSX)
- Legacy /submit_file kept
- Admin bulk import (TXT/CSV/XLSX English-only) -> Google Translate -> pending
- Community audio upload + admin approve/reject
- In-page mic recording posts to: POST /api/submit-audio
- /learn, /support

PWA support:
- /manifest.webmanifest
- /service-worker.js (root scope)
- /offline

SEO / Google:
- /robots.txt
- /sitemap.xml
- ProxyFix for Render (correct https URLs)
- google verification file route

Recorder mode (password protected):
- Recorder password login (/recorder)
- Recorder dashboard (/recorder/dashboard) to quickly record unlimited words/phrases
- Recorder recordings are AUTO-APPROVED and can REPLACE existing approved audio
- Recorder can DELETE approved Oromo audio (no admin approval)
- Public recording stays the same: pending + admin approval
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
import unicodedata

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
app.secret_key = os.environ.get("SECRET_KEY", "dev")

from datetime import timedelta

# True i produksjon/https (Render + Cloudflare). False lokalt på http.
IS_PROD = (os.environ.get("FLASK_ENV") == "production") or bool(os.environ.get("RENDER"))

app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=IS_PROD,
    PERMANENT_SESSION_LIFETIME=timedelta(hours=12),
)

# ✅ IMPORTANT for Render / reverse proxy: makes Flask understand HTTPS + correct host
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_port=1)

logging.basicConfig(level=logging.INFO)
app.logger.setLevel(logging.INFO)

@app.route("/health")
def health():
    return "ok", 200

# Base directory for uploads/db
BASE_DIR = "/var/data" if os.path.exists("/var/data") else os.path.abspath(os.path.dirname(__file__))

UPLOAD_DIR = os.path.join(BASE_DIR, "uploads")
os.makedirs(UPLOAD_DIR, exist_ok=True)

# Upload limit (total request size)
app.config["MAX_CONTENT_LENGTH"] = 25 * 1024 * 1024

DEFAULT_DB = os.path.join(BASE_DIR, "gadaoromo.db")
DB_NAME = (os.environ.get("DB_PATH", "").strip() or DEFAULT_DB)
app.logger.info(f"✅ Using DB_NAME={DB_NAME}")

APP_NAME = os.environ.get("APP_NAME", "Gadaa Dictionary")

ADMIN_MANAGE_PASSWORD = (os.environ.get("ADMIN_MANAGE_PASSWORD") or "").strip()

# If you set WEBSITE_URL in Render env vars, we use it for sitemap/canonical.
WEBSITE_URL = os.environ.get("WEBSITE_URL", "").strip().rstrip("/")
API_URL = os.environ.get("API_URL", "").strip()

SUPPORT_MIN_NOK = int(os.environ.get("SUPPORT_MIN_NOK", "200"))

DONATE_URLS = {
    "custom": os.environ.get("STRIPE_DONATE_CUSTOM_URL", "").strip(),
}

def _safe_url(u: str) -> str:
    u = (u or "").strip()
    if u.startswith("https://") or u.startswith("http://"):
        return u
    return ""

DONATE_URLS = {k: _safe_url(v) for k, v in DONATE_URLS.items()}

@app.before_request
def force_primary_domain():
    if request.path.startswith("/.well-known/"):
        return None
    if request.host == "gadaoromo.onrender.com":
        return redirect("https://gadaadictionary.com" + request.full_path, code=301)

    return None

def _site_base_url() -> str:
    if WEBSITE_URL:
        return WEBSITE_URL.rstrip("/")
    try:
        return (request.url_root or "").rstrip("/")
    except Exception:
        return "https://gadaadictionary.com"

    
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
    if resp.mimetype == "text/html":
        resp.headers.setdefault("Cache-Control", "no-cache")
    return resp

# ------------------ SEO: ROBOTS + SITEMAP ------------------

@app.route("/robots.txt")
def robots_txt():
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
    base = _site_base_url()
    urls = [
        ("/", "daily", "1.0"),
        ("/translate", "daily", "0.9"),
        ("/learn", "weekly", "0.6"),
        ("/support", "monthly", "0.3"),
        ("/submit", "weekly", "0.5"),
        ("/submit_phrase", "weekly", "0.5"),
        ("/recorder", "monthly", "0.2"),
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


@app.route("/.well-known/assetlinks.json")
def assetlinks():
    return send_from_directory(
        os.path.join(app.static_folder, ".well-known"),
        "assetlinks.json",
        mimetype="application/json",
    )

# ------------------ UPLOAD CONFIG (AUDIO) ------------------

IS_RENDER_DISK = os.path.isdir("/var/data")

if IS_RENDER_DISK:
    UPLOAD_FOLDER = "/var/data/uploads"
else:
    UPLOAD_FOLDER = os.path.join(BASE_DIR, "static", "uploads")

os.makedirs(UPLOAD_FOLDER, exist_ok=True)

ALLOWED_AUDIO = {"mp3", "wav", "m4a", "webm", "ogg"}
MAX_AUDIO_MB = int(os.environ.get("MAX_AUDIO_MB", "15"))
MAX_UPLOAD_MB = int(os.environ.get("MAX_UPLOAD_MB", "100"))
app.config["MAX_CONTENT_LENGTH"] = MAX_UPLOAD_MB * 1024 * 1024

# ------------------ PWA ROUTES ------------------

@app.route("/manifest.webmanifest")
def manifest():
    resp = make_response(
        send_from_directory(os.path.join(BASE_DIR, "static"), "manifest.webmanifest")
    )
    resp.headers["Content-Type"] = "application/manifest+json"
    resp.headers["Cache-Control"] = "public, max-age=3600"
    return resp


@app.route("/service-worker.js")
def service_worker():
    resp = make_response(
        send_from_directory(os.path.join(BASE_DIR, "static"), "service-worker.js")
    )
    resp.headers["Content-Type"] = "application/javascript"
    resp.headers["Service-Worker-Allowed"] = "/"
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
        mimetype="image/vnd.microsoft.icon",
    )

# ------------------ GOOGLE VERIFICATION ------------------

@app.route("/googledba38dd4b1b65cfb.html")
def google_verification():
    resp = make_response("google-site-verification: googledba38dd4b1b65cfb.html")
    resp.headers["Content-Type"] = "text/html; charset=utf-8"
    resp.headers["Cache-Control"] = "public, max-age=3600"
    return resp


# ------------------ PUBLIC UPLOADS ROUTE (AUDIO) ------------------

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
    t = (text or "").strip()
    t = t.replace("’", "'").replace("‘", "'").replace("`", "'")
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


def make_search_key(text: str) -> str:
    t = (text or "").strip()
    t = t.replace("’", "'").replace("‘", "'").replace("`", "'")
    t = unicodedata.normalize("NFKC", t)
    t = t.casefold()
    t = re.sub(r"\s+", " ", t).strip()
    return t


# ------------------ COMMUNITY FILE PARSERS (NO GOOGLE) ------------------

def parse_csv_pairs_from_path(path: str):
    # prøv UTF-8 først, fallback latin-1
    for enc in ("utf-8-sig", "utf-8", "latin-1"):
        try:
            with open(path, "r", encoding=enc, newline="") as f:
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

        except UnicodeDecodeError:
            continue

    raise ValueError("Could not decode CSV file.")

def parse_xlsx_pairs_from_path(path: str):
    wb = load_workbook(path, read_only=True, data_only=True)
    ws = wb.active

    seen = set()
    final = []

    for idx, row in enumerate(ws.iter_rows(values_only=True)):
        if not row:
            continue

        a = (row[0] if len(row) > 0 else "") or ""
        b = (row[1] if len(row) > 1 else "") or ""

        # skip header row
        if idx == 0 and str(a).strip().lower() in ("english", "en") and str(b).strip().lower() in ("oromo", "om"):
            continue

        en = normalize_text(str(a))
        om = normalize_text(str(b))

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


# ------------------ ADMIN + RECORDER HELPERS ------------------

def require_admin() -> bool:
    return "admin" in session


def _admin_id() -> int:
    try:
        return int(session.get("admin"))
    except Exception:
        return 0


# ✅ recorder session (password-based)
def require_recorder() -> bool:
    return bool(session.get("recorder") == 1)


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
    Returns URL: '/uploads/xyz.webm'
    """
    fp = (file_path or "").replace("\\", "/").strip()
    if not fp:
        return ""
    if fp.startswith("uploads/"):
        return "/" + fp
    if fp.startswith("/uploads/"):
        return fp
    return "/uploads/" + os.path.basename(fp)


def _audio_abs_path(file_path: str) -> str:
    fp = (file_path or "").replace("\\", "/").strip()
    if not fp:
        return ""
    name = fp.split("/")[-1]
    return os.path.join(UPLOAD_FOLDER, name)


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


def delete_audio_for_entry(entry_type: str, entry_id: int):
    """
    Admin helper: deletes ALL audio rows + files for an entry.
    """
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute(
        "SELECT id, file_path FROM audio WHERE entry_type=? AND entry_id=?",
        (entry_type, entry_id)
    )
    rows = c.fetchall()

    c.execute(
        "DELETE FROM audio WHERE entry_type=? AND entry_id=?",
        (entry_type, entry_id)
    )
    conn.commit()
    conn.close()

    for _aid, fp in rows:
        abs_path = _audio_abs_path(fp)
        if abs_path and os.path.isfile(abs_path):
            try:
                os.remove(abs_path)
            except Exception:
                app.logger.exception(f"Could not delete audio file: {abs_path}")


def delete_audio_for_entry_lang(
    entry_type: str,
    entry_id: int,
    lang: str,
    statuses=("approved", "pending")
) -> int:
    """
    Deletes audio rows + files for a specific entry/lang, filtered by statuses.
    Returns number of rows deleted.
    """
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()

    q_marks = ",".join(["?"] * len(statuses))

    c.execute(f"""
        SELECT id, file_path
        FROM audio
        WHERE entry_type=? AND entry_id=? AND lang=? AND status IN ({q_marks})
    """, (entry_type, entry_id, lang, *statuses))
    rows = c.fetchall()

    c.execute(f"""
        DELETE FROM audio
        WHERE entry_type=? AND entry_id=? AND lang=? AND status IN ({q_marks})
    """, (entry_type, entry_id, lang, *statuses))
    conn.commit()
    conn.close()

    deleted = 0
    for _aid, fp in rows:
        abs_path = _audio_abs_path(fp)
        if abs_path and os.path.isfile(abs_path):
            try:
                os.remove(abs_path)
            except Exception:
                app.logger.exception(f"Could not delete audio file: {abs_path}")
        deleted += 1

    return deleted


# ------------------ DATABASE SETUP ------------------

def init_db():
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()

    c.execute("""
    CREATE TABLE IF NOT EXISTS words (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        english TEXT,
        oromo TEXT,
        english_key TEXT,
        oromo_key TEXT,
        status TEXT
    )
    """)

    c.execute("""
    CREATE TABLE IF NOT EXISTS phrases (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        english TEXT,
        oromo TEXT,
        english_key TEXT,
        oromo_key TEXT,
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
    
def _strip_edge_punct(s: str) -> str:
    return re.sub(r"^[\s\"'“”‘’`]+|[.!?,;:\s\"'“”‘’`]+$", "", s or "").strip()


def ensure_key_columns():
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()

    def has_col(table, col):
        c.execute(f"PRAGMA table_info({table})")
        return any(r[1] == col for r in c.fetchall())

    for table in ("words", "phrases"):
        if not has_col(table, "english_key"):
            c.execute(f"ALTER TABLE {table} ADD COLUMN english_key TEXT")
        if not has_col(table, "oromo_key"):
            c.execute(f"ALTER TABLE {table} ADD COLUMN oromo_key TEXT")

    conn.commit()
    conn.close()

def backfill_keys():
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()

    # words
    c.execute("SELECT id, english, oromo FROM words")
    for wid, en, om in c.fetchall():
        en_norm = normalize_text(en or "")
        om_norm = normalize_text(om or "")
        en_key = make_search_key(_strip_edge_punct(en_norm))
        om_key = make_search_key(_strip_edge_punct(om_norm))
        c.execute(
            "UPDATE words SET english_key=?, oromo_key=? WHERE id=?",
            (en_key, om_key, wid)
        )

    # phrases
    c.execute("SELECT id, english, oromo FROM phrases")
    for pid, en, om in c.fetchall():
        en_norm = normalize_text(en or "")
        om_norm = normalize_text(om or "")
        en_key = make_search_key(_strip_edge_punct(en_norm))
        om_key = make_search_key(_strip_edge_punct(om_norm))
        c.execute(
            "UPDATE phrases SET english_key=?, oromo_key=? WHERE id=?",
            (en_key, om_key, pid)
        )

    conn.commit()
    conn.close()


def ensure_key_indexes():
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("CREATE INDEX IF NOT EXISTS idx_words_english_key ON words(english_key)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_words_oromo_key ON words(oromo_key)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_phrases_english_key ON phrases(english_key)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_phrases_oromo_key ON phrases(oromo_key)")
    conn.commit()
    conn.close()
    
def ensure_phrase_aliases_table():
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()

    c.execute("""
    CREATE TABLE IF NOT EXISTS phrase_aliases (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        phrase_id INTEGER NOT NULL,
        english_alias_key TEXT,
        oromo_alias_key TEXT,
        source TEXT DEFAULT 'auto',
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(phrase_id) REFERENCES phrases(id) ON DELETE CASCADE
    )
    """)

    # Unique indexes (SQLite allows multiple NULLs; fine)
    c.execute("CREATE UNIQUE INDEX IF NOT EXISTS uq_alias_en ON phrase_aliases(english_alias_key)")
    c.execute("CREATE UNIQUE INDEX IF NOT EXISTS uq_alias_om ON phrase_aliases(oromo_alias_key)")

    c.execute("CREATE INDEX IF NOT EXISTS idx_alias_en ON phrase_aliases(english_alias_key)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_alias_om ON phrase_aliases(oromo_alias_key)")

    conn.commit()
    conn.close()


# ✅ Run DB init + migrations at startup
init_db()
ensure_key_columns()
backfill_keys()
ensure_key_indexes()


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

# ------------------ SUGGESTIONS (KEY-BASED, CASE-INSENSITIVE) ------------------

def suggest_terms(term: str, direction: str, limit: int = 8):
    """
    Returns suggestions for the user's input.
    Uses *_key columns => case-insensitive + normalized.
    """
    raw = normalize_text(term)
    if not raw:
        return {"closest": [], "prefix": [], "partial": []}

    tkey = make_search_key(raw)
    if not tkey:
        return {"closest": [], "prefix": [], "partial": []}

    # which table columns to use
    key_col = "oromo_key" if direction == "om_en" else "english_key"
    text_col = "oromo" if direction == "om_en" else "english"

    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()

    # prefix match
    c.execute(f"""
        SELECT {text_col}
        FROM words
        WHERE status='approved' AND {key_col} LIKE ?
        LIMIT ?
    """, (tkey + "%", limit))
    prefix = [r[0] for r in c.fetchall() if r and r[0]]

    # partial match
    c.execute(f"""
        SELECT {text_col}
        FROM words
        WHERE status='approved' AND {key_col} LIKE ?
        LIMIT ?
    """, ("%" + tkey + "%", limit))
    partial = [r[0] for r in c.fetchall() if r and r[0]]

    # candidates for "closest" (use last 3000 for speed)
    c.execute(f"""
        SELECT {text_col}
        FROM words
        WHERE status='approved'
        ORDER BY id DESC
        LIMIT 3000
    """)
    candidates = [r[0] for r in c.fetchall() if r and r[0]]
    conn.close()

    # closest match (run on normalized form to be fair)
    # map: normalized -> original
    norm_map = {}
    norm_list = []
    for cand in candidates:
        nk = make_search_key(cand)
        if nk and nk not in norm_map:
            norm_map[nk] = cand
            norm_list.append(nk)

    closest_norm = get_close_matches(tkey, norm_list, n=limit, cutoff=0.75)
    closest = [norm_map[n] for n in closest_norm if n in norm_map]

    def dedup(seq):
        seen = set()
        out = []
        for x in seq:
            if x not in seen:
                seen.add(x)
                out.append(x)
        return out

    return {"closest": dedup(closest), "prefix": dedup(prefix), "partial": dedup(partial)}


# ------------------ AUTO LANGUAGE DETECT (KEY-BASED, PUNCT-SAFE) ------------------

_WORD_RE = re.compile(r"[A-Za-z0-9']+")

def detect_direction_auto(text: str) -> str:
    """
    Decides whether user typed Oromo or English.
    Uses *_key columns for matching (case-insensitive).
    """
    t = normalize_text(text)
    if not t:
        return "en_om"

    # extract "word tokens" without punctuation
    tokens = _WORD_RE.findall(t)
    if not tokens:
        return "en_om"

    filtered = [w for w in tokens if w.casefold() not in EN_STOP and w.casefold() not in OROMO_STOP]
    if not filtered:
        filtered = tokens

    full_key = make_search_key(_strip_edge_punct(t))

    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()

    or_score = 0
    en_score = 0

    # token scoring via keys
    for w in filtered:
        wk = make_search_key(w)

        c.execute("SELECT 1 FROM words WHERE status='approved' AND oromo_key=? LIMIT 1", (wk,))
        if c.fetchone():
            or_score += 1

        c.execute("SELECT 1 FROM words WHERE status='approved' AND english_key=? LIMIT 1", (wk,))
        if c.fetchone():
            en_score += 1

    # phrase scoring via keys (stronger weight)
    c.execute("SELECT 1 FROM phrases WHERE status='approved' AND oromo_key=? LIMIT 1", (full_key,))
    if c.fetchone():
        or_score += 4

    c.execute("SELECT 1 FROM phrases WHERE status='approved' AND english_key=? LIMIT 1", (full_key,))
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

    # Try exact phrase match using *_key (case-insensitive)
    t_key = make_search_key(_strip_edge_punct(t))

    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()

    if t_key:
        if direction == "om_en":
            c.execute(
                "SELECT id, english FROM phrases WHERE status='approved' AND oromo_key=?",
                (t_key,)
            )
            row = c.fetchone()
            if row:
                conn.close()
                return row[1], 1, 1
        else:
            c.execute(
                "SELECT id, oromo FROM phrases WHERE status='approved' AND english_key=?",
                (t_key,)
            )
            row = c.fetchone()
            if row:
                conn.close()
                return row[1], 1, 1

    # Single-word exact match using *_key
    tokens = t.split()
    if len(tokens) == 1:
        wkey = make_search_key(_strip_edge_punct(tokens[0]))
        if wkey:
            if direction == "om_en":
                c.execute(
                    "SELECT id, english FROM words WHERE status='approved' AND oromo_key=?",
                    (wkey,)
                )
                row = c.fetchone()
                if row:
                    conn.close()
                    return row[1], 1, 0
            else:
                c.execute(
                    "SELECT id, oromo FROM words WHERE status='approved' AND english_key=?",
                    (wkey,)
                )
                row = c.fetchone()
                if row:
                    conn.close()
                    return row[1], 1, 0

    # Word-by-word fallback using *_key (case-insensitive)
    out = []
    for w in tokens:
        wk = make_search_key(_strip_edge_punct(w))
        if not wk:
            out.append(w)
            continue

        if direction == "om_en":
            c.execute("SELECT english FROM words WHERE status='approved' AND oromo_key=?", (wk,))
            r = c.fetchone()
            out.append(r[0] if r else w)
        else:
            c.execute("SELECT oromo FROM words WHERE status='approved' AND english_key=?", (wk,))
            r = c.fetchone()
            out.append(r[0] if r else w)

    conn.close()
    return " ".join(out), 0, 0


import re

EN_FILLERS = {"please"}
EN_ARTICLES = {"a", "an", "the"}

def key_for(text: str) -> str:
    """One key rule everywhere."""
    return make_search_key(_strip_edge_punct(normalize_text(text)))

def generate_english_alias_texts(english: str) -> list[str]:
    """
    Generate a small set of safe aliases (not too aggressive).
    You can expand later.
    """
    s = normalize_text(english)
    if not s:
        return []

    toks = s.split()
    aliases = {s}

    # Remove trailing "please"
    if toks and toks[-1].casefold() in EN_FILLERS:
        aliases.add(" ".join(toks[:-1]))

    # Remove articles (a/an/the) - lightweight
    no_articles = [t for t in toks if t.casefold() not in EN_ARTICLES]
    if no_articles and no_articles != toks:
        aliases.add(" ".join(no_articles))

    # Remove both: articles + trailing please
    toks2 = no_articles
    if toks2 and toks2[-1].casefold() in EN_FILLERS:
        aliases.add(" ".join(toks2[:-1]))

    # De-dup, keep non-empty
    out = []
    seen = set()
    for a in aliases:
        a = normalize_text(a)
        if a and a not in seen:
            seen.add(a)
            out.append(a)
    return out

def generate_oromo_alias_texts(oromo: str) -> list[str]:
    """
    Oromo aliases: keep conservative.
    For now, just the original normalized text.
    You can add Oromo-specific variants later.
    """
    s = normalize_text(oromo)
    return [s] if s else []

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
        raw = request.form.get("word", "")
        word = make_search_key(raw)

        c.execute("""
            SELECT id, english, oromo
            FROM words
            WHERE status='approved' AND (english_key=? OR oromo_key=?)
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


# Make sure these exist somewhere in your file/module:
# - DB_NAME
# - normalize_text
# - make_search_key
# - detect_direction_auto
# - _strip_edge_punct
# - translate_multipart_text
# - record_search
# - suggest_terms
# - get_trending
# - get_approved_audio
# - get_approved_oromo_audio_ids

# Tokenizer used for "single-word" detection (keeps punctuation separate)
_TOKEN_RE = re.compile(r"\s+|[^\w\s]+|[\w']+", re.UNICODE)


def build_key_candidates(s: str):
    """Same key strategy as translate_text(): robust vs punctuation/spacing mismatch."""
    s = normalize_text(s)
    cands = []

    k1 = make_search_key(s)
    if k1:
        cands.append(k1)

    s2 = _strip_edge_punct(s)
    k2 = make_search_key(s2)
    if k2 and k2 not in cands:
        cands.append(k2)

    s3 = re.sub(r"\s+", " ", s2).strip()
    k3 = make_search_key(s3)
    if k3 and k3 not in cands:
        cands.append(k3)

    return cands

def phrase_key_candidates(s: str):
    s = normalize_text(s)
    cands = []
    k1 = make_search_key(s)                       # keep punctuation if present
    if k1:
        cands.append(k1)

    s2 = _strip_edge_punct(s)                     # remove edge punctuation
    k2 = make_search_key(s2)
    if k2 and k2 not in cands:
        cands.append(k2)

    return cands


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

        clean_exact = normalize_text(text)
        key_candidates = build_key_candidates(text)

        conn = sqlite3.connect(DB_NAME)
        c = conn.cursor()

        # --- exact phrase match (case-insensitive via *_key) ---
        if key_candidates:
            if direction == "om_en":
                for k in key_candidates:
                    pr = c.execute(
                        "SELECT id FROM phrases WHERE status='approved' AND oromo_key=? LIMIT 1",
                        (k,)
                    ).fetchone()
                    if pr:
                        matched = {"type": "phrase", "id": pr[0]}
                        audio = get_approved_audio("phrase", pr[0])
                        break
            else:
                for k in key_candidates:
                    pr = c.execute(
                        "SELECT id FROM phrases WHERE status='approved' AND english_key=? LIMIT 1",
                        (k,)
                    ).fetchone()
                    if pr:
                        matched = {"type": "phrase", "id": pr[0]}
                        audio = get_approved_audio("phrase", pr[0])
                        break

        # --- exact word match (only if input is truly a single word-like token) ---
        if not matched:
            tokens = [t for t in _TOKEN_RE.findall(clean_exact) if not t.isspace()]
            word_tokens = [t for t in tokens if re.fullmatch(r"[\w']+", t)]
            # exactly one word token, and nothing else word-like
            if len(word_tokens) == 1 and len([t for t in tokens if re.fullmatch(r"[\w']+", t)]) == 1:
                wkey = make_search_key(word_tokens[0])
                if wkey:
                    if direction == "om_en":
                        wr = c.execute(
                            "SELECT id FROM words WHERE status='approved' AND oromo_key=? LIMIT 1",
                            (wkey,)
                        ).fetchone()
                    else:
                        wr = c.execute(
                            "SELECT id FROM words WHERE status='approved' AND english_key=? LIMIT 1",
                            (wkey,)
                        ).fetchone()

                    if wr:
                        matched = {"type": "word", "id": wr[0]}
                        audio = get_approved_audio("word", wr[0])

        conn.close()

        # ✅ IMPORTANT: use multipart translator (handles commas + sentences correctly)
        translated, is_exact, is_phrase = translate_multipart_text(text, direction)

        record_search(text, direction, is_phrase, is_exact)
        result = translated

        # suggestions only for single word not exact
        # (use improved single-word detection rather than split())
        if not is_exact:
            tokens = [t for t in _TOKEN_RE.findall(clean_exact) if not t.isspace()]
            word_tokens = [t for t in tokens if re.fullmatch(r"[\w']+", t)]
            if len(word_tokens) == 1:
                suggestions = suggest_terms(word_tokens[0], direction)

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


# ------------------ MULTI-SENTENCE TRANSLATION ------------------

_WORDLIKE_RE = re.compile(r"[\w']+", re.UNICODE)
_TOKEN_RE = re.compile(r"\s+|[^\w\s]+|[\w']+", re.UNICODE)
_BOUNDARY_RE = re.compile(r"[.!?,;:]")

def _strip_trailing_punct(s: str) -> str:
    # remove trailing boundary punctuation only (.,!?;:)
    return re.sub(r"[.!?,;:]+$", "", (s or "").strip())

def upsert_phrase_aliases(phrase_id: int, english: str, oromo: str, source: str = "auto"):
    """
    Insert alias keys for a phrase. Safe to call multiple times.
    """
    en_aliases = generate_english_alias_texts(english)
    om_aliases = generate_oromo_alias_texts(oromo)

    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()

    # Clear old aliases for this phrase (simple & safe)
    c.execute("DELETE FROM phrase_aliases WHERE phrase_id=?", (phrase_id,))

    # Insert new aliases
    for a in en_aliases:
        k = key_for(a)
        if k:
            c.execute("""
                INSERT OR IGNORE INTO phrase_aliases (phrase_id, english_alias_key, source)
                VALUES (?, ?, ?)
            """, (phrase_id, k, source))

    for a in om_aliases:
        k = key_for(a)
        if k:
            c.execute("""
                INSERT OR IGNORE INTO phrase_aliases (phrase_id, oromo_alias_key, source)
                VALUES (?, ?, ?)
            """, (phrase_id, k, source))

    conn.commit()
    conn.close()


def split_segments(text: str):
    """Return list of (segment_text, punctuation, trailing_ws)."""
    t = normalize_text(text)
    if not t:
        return []

    out, buf = [], []
    i, n = 0, len(t)

    while i < n:
        ch = t[i]
        if _BOUNDARY_RE.match(ch):
            seg = "".join(buf)
            buf = []

            punct = []
            while i < n and _BOUNDARY_RE.match(t[i]):
                punct.append(t[i]); i += 1

            ws = []
            while i < n and t[i].isspace():
                ws.append(t[i]); i += 1

            out.append((seg, "".join(punct), "".join(ws)))
        else:
            buf.append(ch); i += 1

    tail = "".join(buf)
    if tail.strip():
        out.append((tail, "", ""))

    return out

def _phrase_lookup(cur, direction: str, k: str):
    if direction == "om_en":
        row = cur.execute(
            "SELECT english FROM phrases WHERE status='approved' AND oromo_key=? LIMIT 1",
            (k,)
        ).fetchone()
    else:
        row = cur.execute(
            "SELECT oromo FROM phrases WHERE status='approved' AND english_key=? LIMIT 1",
            (k,)
        ).fetchone()
    return row[0] if row else None

def _word_lookup(cur, direction: str, k: str):
    if direction == "om_en":
        row = cur.execute(
            "SELECT english FROM words WHERE status='approved' AND oromo_key=? LIMIT 1",
            (k,)
        ).fetchone()
    else:
        row = cur.execute(
            "SELECT oromo FROM words WHERE status='approved' AND english_key=? LIMIT 1",
            (k,)
        ).fetchone()
    return row[0] if row else None

def translate_segment_best(segment_text: str, direction: str, cur, max_phrase_words: int = 12):
    """
    Translate one segment using longest-phrase-first over word positions.
    Preserves original spacing/punctuation inside the segment.
    """
    if not segment_text or not segment_text.strip():
        return "", 0, 0

    # Tokenize into pieces but we also need a word list for phrase scanning
    tokens = _TOKEN_RE.findall(segment_text)

    # Build mapping from "word index" to token positions
    word_positions = []  # list of (token_idx, word_text)
    for ti, tok in enumerate(tokens):
        if _WORDLIKE_RE.fullmatch(tok):
            word_positions.append((ti, tok))

    # If no words, return as-is
    if not word_positions:
        return segment_text, 0, 0

    # Convenience: list of word strings (in order)
    words = [w for _, w in word_positions]
    n_words = len(words)

    out_tokens = tokens[:]  # we'll replace words/phrases in place
    consumed_word = [False] * n_words
    any_exact = 0
    any_phrase = 0

    i = 0
    while i < n_words:
        if consumed_word[i]:
            i += 1
            continue

        # Try longest phrase starting at i
        found_translation = None
        found_len = 0

        max_len = min(max_phrase_words, n_words - i)
        for L in range(max_len, 1, -1):  # phrases of length >= 2
            phrase_text = " ".join(words[i:i+L])
            k = key_for(phrase_text)
            if not k:
                continue
            tr = _phrase_lookup(cur, direction, k)
            if tr:
                found_translation = tr
                found_len = L
                break

        if found_translation:
            any_exact = 1
            any_phrase = 1

            # Replace the first word token with translation, blank out the rest words in phrase
            first_token_idx = word_positions[i][0]
            out_tokens[first_token_idx] = found_translation

            # Blank out the remaining word tokens and any immediate punctuation attached between them
            for j in range(i, i + found_len):
                consumed_word[j] = True
                if j == i:
                    continue
                tok_idx = word_positions[j][0]
                out_tokens[tok_idx] = ""  # remove word itself

            i += found_len
            continue

        # No phrase found => translate single word
        w = words[i]
        k = key_for(w)
        tr = _word_lookup(cur, direction, k) if k else None
        if tr:
            any_exact = 1
            out_tokens[word_positions[i][0]] = tr
        # else keep original word
        consumed_word[i] = True
        i += 1

    # Join, then clean extra spaces caused by removed tokens (keep user punctuation)
    result = "".join(out_tokens)
    result = re.sub(r"\s+", " ", result).strip()
    return result, any_exact, any_phrase

def translate_multipart_text(text: str, direction: str):
    parts = split_segments(text)
    if not parts:
        return "", 0, 0

    out = []
    any_exact = 0
    any_phrase = 0

    for seg_text, punct, ws in parts:
        if seg_text:
            tr, ex, ph = translate_text(seg_text, direction)

            # ✅ IMPORTANT: avoid doubled punctuation when phrase already ends with . or ?
            # If input has punctuation, input punctuation should win.
            if ph and punct:
                tr = _strip_trailing_punct(tr)

            out.append(tr)
            any_exact |= ex
            any_phrase |= ph
        else:
            out.append(seg_text)

        out.append(punct)
        out.append(ws)

    return "".join(out), int(any_exact), int(any_phrase)

def lookup_phrase_via_alias(cur, direction: str, alias_key: str):
    if direction == "om_en":
        row = cur.execute("""
            SELECT p.english
            FROM phrase_aliases a
            JOIN phrases p ON p.id = a.phrase_id
            WHERE p.status='approved' AND a.oromo_alias_key=?
            LIMIT 1
        """, (alias_key,)).fetchone()
    else:
        row = cur.execute("""
            SELECT p.oromo
            FROM phrase_aliases a
            JOIN phrases p ON p.id = a.phrase_id
            WHERE p.status='approved' AND a.english_alias_key=?
            LIMIT 1
        """, (alias_key,)).fetchone()
    return row[0] if row else None

def lookup_word(cur, direction: str, w_key: str):
    if direction == "om_en":
        row = cur.execute("""
            SELECT english FROM words WHERE status='approved' AND oromo_key=? LIMIT 1
        """, (w_key,)).fetchone()
    else:
        row = cur.execute("""
            SELECT oromo FROM words WHERE status='approved' AND english_key=? LIMIT 1
        """, (w_key,)).fetchone()
    return row[0] if row else None

def translate_segment_longest_phrase(cur, segment_text: str, direction: str, max_phrase_words: int = 12):
    """
    Greedy longest-phrase-first over words in the segment.
    Returns (translated_segment, any_exact, any_phrase).
    """
    seg = normalize_text(segment_text)
    if not seg:
        return "", 0, 0

    words = seg.split()
    out = []
    i = 0
    any_exact = 0
    any_phrase = 0

    while i < len(words):
        best_tr = None
        best_len = 0

        Lmax = min(max_phrase_words, len(words) - i)
        for L in range(Lmax, 1, -1):  # phrase length >= 2
            phrase_text = " ".join(words[i:i+L])
            k = key_for(phrase_text)
            if not k:
                continue
            tr = lookup_phrase_via_alias(cur, direction, k)
            if tr:
                best_tr = tr
                best_len = L
                break

        if best_tr:
            out.append(best_tr)
            any_exact = 1
            any_phrase = 1
            i += best_len
            continue

        # word fallback
        wk = key_for(words[i])
        trw = lookup_word(cur, direction, wk) if wk else None
        if trw:
            out.append(trw)
            any_exact = 1
        else:
            out.append(words[i])
        i += 1

    return " ".join(out), int(any_exact), int(any_phrase)


# ------------------ PUBLIC SUBMISSION (WORDS) ------------------

@app.route("/submit", methods=["GET", "POST"])
def submit():
    msg = None

    if request.method == "POST":
        mode = (request.form.get("mode") or "").strip().lower()
        f = request.files.get("file")

        # ---------- FILE MODE ----------
        if mode == "file" or (f and f.filename):
            if not f or not f.filename:
                msg = "Please choose a CSV or XLSX file."
                return render_template("submit.html", msg=msg)

            import tempfile

            filename = (f.filename or "").lower().strip()

            # Save upload to temp file (streamed, avoids RAM spike)
            with tempfile.NamedTemporaryFile(delete=False, suffix=filename) as tmp:
                f.save(tmp.name)
                path = tmp.name

            try:
                if filename.endswith(".csv"):
                    pairs = parse_csv_pairs_from_path(path)
                elif filename.endswith(".xlsx"):
                    pairs = parse_xlsx_pairs_from_path(path)
                else:
                    msg = "Only .csv or .xlsx files are allowed."
                    return render_template("submit.html", msg=msg)
            except Exception as e:
                app.logger.exception(f"submit (words) file parse error: {repr(e)}")
                msg = "Could not read the file. Please check its format."
                return render_template("submit.html", msg=msg)
            finally:
                try:
                    os.remove(path)
                except OSError:
                    pass

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
                c.execute(
                    "SELECT 1 FROM words WHERE english=? OR oromo=? LIMIT 1",
                    (en, om),
                )
                if c.fetchone():
                    skipped += 1
                    continue

                c.execute(
                    "INSERT INTO words (english, oromo, status) VALUES (?, ?, 'pending')",
                    (en, om),
                )
                inserted += 1

            conn.commit()
            conn.close()

            msg = (
                f"Thanks! File submitted. "
                f"Added: {inserted} | Skipped duplicates: {skipped}. "
                f"Waiting for admin approval."
            )
            return render_template("submit.html", msg=msg)
        
        # ---------- TEXT MODE ----------
        english_raw = (request.form.get("english") or "").strip()
        oromo_raw = (request.form.get("oromo") or "").strip()
        
        english_key = make_search_key(english_raw)
        oromo_key = make_search_key(oromo_raw)

        if not english_key or not oromo_key:
            msg = "Please provide both English and Oromo."
            return render_template("submit.html", msg=msg)
        

        conn = sqlite3.connect(DB_NAME)
        c = conn.cursor()
        
        # duplicate check via *_key (case-insensitive)
        c.execute(
            "SELECT 1 FROM words WHERE english_key=? OR oromo_key=?",
            (english_key, oromo_key),
        )
        if c.fetchone():
            conn.close()
            msg = "This word already exists (or is pending). Try another."
            return render_template("submit.html", msg=msg)
        
         # insert original + key
         
        c.execute(
            "INSERT INTO words (english, oromo,english_key, oromo_key, status) VALUES (?, ?, ?, ?, 'pending')",
            (english_raw, oromo_raw, english_key, oromo_key),
        )
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

        # ---------- FILE MODE ----------
        if mode == "file" or (f and f.filename):
            if not f or not f.filename:
                msg = "Please choose a CSV or XLSX file."
                return render_template("submit_phrase.html", msg=msg)

            import tempfile

            filename = (f.filename or "").lower().strip()

            # Save upload to temp file (no RAM spike)
            with tempfile.NamedTemporaryFile(delete=False, suffix=filename) as tmp:
                f.save(tmp.name)
                path = tmp.name

            try:
                if filename.endswith(".csv"):
                    pairs = parse_csv_pairs_from_path(path)
                elif filename.endswith(".xlsx"):
                    pairs = parse_xlsx_pairs_from_path(path)
                else:
                    msg = "Only .csv or .xlsx files are allowed."
                    return render_template("submit_phrase.html", msg=msg)
            except Exception as e:
                app.logger.exception(f"submit_phrase file parse error: {repr(e)}")
                msg = "Could not read the file. Please check its format."
                return render_template("submit_phrase.html", msg=msg)
            finally:
                try:
                    os.remove(path)
                except OSError:
                    pass

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
                c.execute(
                    "SELECT 1 FROM phrases WHERE english=? OR oromo=? LIMIT 1",
                    (en, om),
                )
                if c.fetchone():
                    skipped += 1
                    continue

                c.execute(
                    "INSERT INTO phrases (english, oromo, status) VALUES (?, ?, 'pending')",
                    (en, om),
                )
                inserted += 1

            conn.commit()
            conn.close()

            msg = (
                f"Thanks! Phrase file submitted. "
                f"Added: {inserted} | Skipped duplicates: {skipped}. "
                f"Waiting for admin approval."
            )
            return render_template("submit_phrase.html", msg=msg)

        # ---------- TEXT MODE ----------
        english = normalize_text(request.form.get("english", ""))
        oromo = normalize_text(request.form.get("oromo", ""))

        if not english or not oromo:
            msg = "Please provide both English and Oromo phrase."
            return render_template("submit_phrase.html", msg=msg)

        conn = sqlite3.connect(DB_NAME)
        c = conn.cursor()

        c.execute(
            "SELECT 1 FROM phrases WHERE english=? OR oromo=?",
            (english, oromo),
        )
        if c.fetchone():
            conn.close()
            msg = "This phrase already exists (or is pending). Try another."
            return render_template("submit_phrase.html", msg=msg)

        c.execute(
            "INSERT INTO phrases (english, oromo, status) VALUES (?, ?, 'pending')",
            (english, oromo),
        )
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

        import tempfile

        filename = (f.filename or "").lower().strip()

        # Save upload to temp file (prevents RAM spike)
        with tempfile.NamedTemporaryFile(delete=False, suffix=filename) as tmp:
            f.save(tmp.name)
            path = tmp.name

        try:
            if filename.endswith(".csv"):
                pairs = parse_csv_pairs_from_path(path)
            elif filename.endswith(".xlsx"):
                pairs = parse_xlsx_pairs_from_path(path)
            else:
                msg = "Only .csv or .xlsx files are allowed."
                return render_template("submit_file.html", msg=msg)
        except Exception as e:
            app.logger.exception(f"submit_file parse error: {repr(e)}")
            msg = "Could not read the file. Please check its format."
            return render_template("submit_file.html", msg=msg)
        finally:
            try:
                os.remove(path)
            except OSError:
                pass

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
            c.execute(
                "SELECT 1 FROM words WHERE english=? OR oromo=? LIMIT 1",
                (en, om),
            )
            if c.fetchone():
                skipped += 1
                continue

            c.execute(
                "INSERT INTO words (english, oromo, status) VALUES (?, ?, 'pending')",
                (en, om),
            )
            inserted += 1

        conn.commit()
        conn.close()

        msg = (
            f"Thanks! File submitted. "
            f"Added: {inserted} | Skipped duplicates: {skipped}. "
            f"Waiting for admin approval."
        )
        return render_template("submit_file.html", msg=msg)

    return render_template("submit_file.html", msg=msg)

# ------------------ RECORDER LOGIN + DASHBOARD ------------------
# Requires env var: RECORDER_PASSWORD

@app.route("/recorder", methods=["GET", "POST"])
def recorder_login():
    msg = None
    if request.method == "POST":
        pw = (request.form.get("password") or "").strip()
        correct = os.environ.get("RECORDER_PASSWORD", "").strip()
        if correct and pw == correct:
            session["recorder"] = 1
            return redirect("/recorder/dashboard")
        msg = "Invalid recorder password."
    return render_template("recorder_login.html", msg=msg)


@app.route("/recorder/logout")
def recorder_logout():
    session.pop("recorder", None)
    return redirect("/")


@app.route("/recorder/dashboard")
def recorder_dashboard():
    if not require_recorder():
        return redirect("/recorder")

    q = normalize_text(request.args.get("q", "") or "")

    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()

    if q:
        like = "%" + q + "%"
        c.execute("""
            SELECT id, english, oromo
            FROM words
            WHERE status='approved' AND (english LIKE ? OR oromo LIKE ?)
            ORDER BY english ASC
            LIMIT 200
        """, (like, like))
        words = c.fetchall()

        c.execute("""
            SELECT id, english, oromo
            FROM phrases
            WHERE status='approved' AND (english LIKE ? OR oromo LIKE ?)
            ORDER BY id DESC
            LIMIT 200
        """, (like, like))
        phrases = c.fetchall()
    else:
        c.execute("""
            SELECT id, english, oromo
            FROM words
            WHERE status='approved'
            ORDER BY english ASC
            LIMIT 100
        """)
        words = c.fetchall()

        c.execute("""
            SELECT id, english, oromo
            FROM phrases
            WHERE status='approved'
            ORDER BY id DESC
            LIMIT 100
        """)
        phrases = c.fetchall()

    conn.close()

    approved_word_ids = get_approved_oromo_audio_ids("word")
    approved_phrase_ids = get_approved_oromo_audio_ids("phrase")

    return render_template(
        "recorder_dashboard.html",
        q=q,
        words=words,
        phrases=phrases,
        approved_word_ids=approved_word_ids,
        approved_phrase_ids=approved_phrase_ids
    )


@app.route("/recorder/entry/<entry_type>/<int:entry_id>")
def recorder_entry(entry_type, entry_id):
    if not require_recorder():
        return redirect("/recorder")

    entry_type = (entry_type or "").strip().lower()
    if entry_type not in ("word", "phrase"):
        abort(400)

    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()

    if entry_type == "word":
        c.execute(
            "SELECT id, english, oromo FROM words WHERE id=? AND status='approved'",
            (entry_id,)
        )
    else:
        c.execute(
            "SELECT id, english, oromo FROM phrases WHERE id=? AND status='approved'",
            (entry_id,)
        )

    row = c.fetchone()
    conn.close()

    if not row:
        abort(404)

    audio = get_approved_audio(entry_type, entry_id)
    return render_template(
        "recorder_entry.html",
        entry_type=entry_type,
        entry_id=entry_id,
        english=row[1],
        oromo=row[2],
        audio=audio
    )


# ------------------ RECORDER API: GET CURRENT AUDIO + DELETE ------------------

from werkzeug.exceptions import RequestEntityTooLarge


@app.errorhandler(RequestEntityTooLarge)
def handle_413(e):
    # JSON for API endpoints
    if request.path.startswith("/api/") or request.path.startswith("/recorder/api/"):
        return jsonify({"ok": False, "error": "File too large. Please upload a smaller file."}), 413

    # HTML for normal pages
    msg = "File too large. Please upload a smaller file (or increase MAX_UPLOAD_MB)."
    if request.path.startswith("/submit_phrase"):
        return render_template("submit_phrase.html", msg=msg), 413
    if request.path.startswith("/submit_file"):
        return render_template("submit_file.html", msg=msg), 413
    if request.path.startswith("/submit"):
        return render_template("submit.html", msg=msg), 413

    return "File too large.", 413


@app.route("/recorder/api/audio", methods=["GET"])
def recorder_api_audio_get():
    """
    Recorder-only:
    GET /recorder/api/audio?entry_type=word&entry_id=123
    Returns approved audio urls for that entry (dict)
    """
    if not require_recorder():
        return jsonify({"ok": False, "error": "Recorder login required"}), 401

    entry_type = (request.args.get("entry_type") or "").strip().lower()
    entry_id_raw = (request.args.get("entry_id") or "").strip()

    if entry_type not in ("word", "phrase"):
        return jsonify({"ok": False, "error": "Invalid entry_type"}), 400
    if not entry_id_raw.isdigit():
        return jsonify({"ok": False, "error": "Invalid entry_id"}), 400

    entry_id = int(entry_id_raw)
    audio = get_approved_audio(entry_type, entry_id)
    return jsonify({"ok": True, "audio": audio})


@app.route("/recorder/api/delete-audio", methods=["POST"])
def recorder_api_delete_audio():
    """
    Recorder-only:
    POST { entry_type, entry_id, lang='oromo' }
    Deletes APPROVED Oromo audio (and file) for that entry.
    """
    if not require_recorder():
        return jsonify({"ok": False, "error": "Recorder login required"}), 401

    entry_type = (request.form.get("entry_type") or "").strip().lower()
    entry_id_raw = (request.form.get("entry_id") or "").strip()
    lang = (request.form.get("lang") or "oromo").strip().lower()

    if entry_type not in ("word", "phrase"):
        return jsonify({"ok": False, "error": "Invalid entry_type"}), 400
    if not entry_id_raw.isdigit():
        return jsonify({"ok": False, "error": "Invalid entry_id"}), 400
    if lang != "oromo":
        return jsonify({"ok": False, "error": "Only Oromo audio is allowed."}), 400

    entry_id = int(entry_id_raw)

    deleted = delete_audio_for_entry_lang(entry_type, entry_id, lang, statuses=("approved",))
    return jsonify({"ok": True, "deleted": deleted})


@app.route("/recorder/api/submit-audio", methods=["POST"])
def recorder_api_submit_audio():
    if not require_recorder():
        return jsonify({"ok": False, "error": "Recorder login required"}), 401

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

    # entry must exist + approved
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

    # ✅ Recorder uploads: replace existing audio (approved + pending) for this entry/lang
    conn.close()
    delete_audio_for_entry_lang(entry_type, entry_id, lang, statuses=("approved", "pending"))

    original = secure_filename(f.filename)
    ext = original.rsplit(".", 1)[1].lower()
    new_name = f"{entry_type}_{entry_id}_{lang}_{uuid4().hex}.{ext}"
    save_path = os.path.join(UPLOAD_FOLDER, new_name)
    f.save(save_path)

    rel_path = f"uploads/{new_name}"

    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    # ✅ auto-approve for recorder
    c.execute("""
        INSERT INTO audio (entry_type, entry_id, lang, file_path, status)
        VALUES (?, ?, ?, ?, 'approved')
    """, (entry_type, entry_id, lang, rel_path))
    conn.commit()
    conn.close()

    url = _public_audio_url(rel_path)
    return jsonify({"ok": True, "message": "Saved ✅ Published now.", "url": url})


# ------------------ API AUDIO SUBMISSION (PUBLIC + RECORDER MODE) ------------------

def _handle_audio_submission(is_recorder: bool):
    entry_type = (request.form.get("entry_type") or "").strip().lower()
    entry_id_raw = (request.form.get("entry_id") or "").strip()
    lang = (request.form.get("lang") or "oromo").strip().lower()

    if entry_type not in ("word", "phrase"):
        return jsonify({"ok": False, "error": "Invalid entry_type"}), 400
    if not entry_id_raw.isdigit():
        return jsonify({"ok": False, "error": "Invalid entry_id"}), 400
    if lang != "oromo":
        return jsonify({"ok": False, "error": "Only Oromo audio is allowed."}), 400

    entry_id = int(entry_id_raw)

    f = request.files.get("audio")
    if not f or not f.filename:
        return jsonify({"ok": False, "error": "Missing audio file"}), 400

    original = secure_filename(f.filename)
    if "." not in original:
        return jsonify({"ok": False, "error": "Audio file must have an extension (webm/mp3/wav/m4a/ogg)."}), 400
    if not allowed_audio(original):
        return jsonify({"ok": False, "error": "Allowed audio: mp3, wav, m4a, webm, ogg"}), 400

    ext = original.rsplit(".", 1)[1].lower()

    # ✅ connect with timeout (prevents “stuck forever” on DB lock)
    conn = sqlite3.connect(DB_NAME, timeout=30)
    c = conn.cursor()
    try:
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA synchronous=NORMAL;")

        # Entry must exist + be approved
        if entry_type == "word":
            c.execute("SELECT id FROM words WHERE id=? AND status='approved'", (entry_id,))
        else:
            c.execute("SELECT id FROM phrases WHERE id=? AND status='approved'", (entry_id,))
        row = c.fetchone()
        if not row:
            return jsonify({"ok": False, "error": "Entry not found or not approved"}), 404

        if is_recorder:
            # ✅ IMPORTANT: do deletes BEFORE saving file + inserting
            conn.close()
            delete_audio_for_entry_lang(entry_type, entry_id, lang, statuses=("approved", "pending"))

            conn = sqlite3.connect(DB_NAME, timeout=30)
            c = conn.cursor()
            conn.execute("PRAGMA journal_mode=WAL;")
            conn.execute("PRAGMA synchronous=NORMAL;")
        else:
            # Public users: block if approved exists
            c.execute("""
                SELECT 1 FROM audio
                WHERE entry_type=? AND entry_id=? AND lang=? AND status='approved'
                LIMIT 1
            """, (entry_type, entry_id, lang))
            if c.fetchone():
                return jsonify({"ok": False, "error": "This entry already has approved audio."}), 409

        # Save file
        new_name = f"{entry_type}_{entry_id}_{lang}_{uuid4().hex}.{ext}"
        save_path = os.path.join(UPLOAD_FOLDER, new_name)
        f.save(save_path)

        rel_path = f"uploads/{new_name}"
        status = "approved" if is_recorder else "pending"

        c.execute("""
            INSERT INTO audio (entry_type, entry_id, lang, file_path, status)
            VALUES (?, ?, ?, ?, ?)
        """, (entry_type, entry_id, lang, rel_path, status))

        conn.commit()

        return jsonify({
            "ok": True,
            "message": ("Saved ✅ Published now." if is_recorder else "Oromo audio submitted for admin approval."),
            "status": status,
            "url": _public_audio_url(rel_path)
        })

    except sqlite3.OperationalError as e:
        return jsonify({"ok": False, "error": f"Database error: {str(e)}"}), 500

    finally:
        try:
            conn.close()
        except Exception:
            pass


# ------------------ COMMUNITY AUDIO UPLOAD PAGE (OROMO ONLY) ------------------

@app.route("/upload_audio/<entry_type>/<int:entry_id>/<lang>", methods=["GET", "POST"])
def upload_audio(entry_type, entry_id, lang):
    """
    Manual file upload page (public).
    ✅ Oromo ONLY
    ✅ Allow unlimited pending submissions
    ✅ Block only if an APPROVED Oromo audio already exists for this entry
    """
    entry_type = (entry_type or "").strip().lower()
    lang = (lang or "").strip().lower()

    if entry_type not in ("word", "phrase"):
        return "Invalid entry type", 400

    if lang != "oromo":
        return "Only Oromo audio is allowed.", 400

    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()

    if entry_type == "word":
        c.execute("SELECT id, english, oromo FROM words WHERE id=? AND status='approved'", (entry_id,))
    else:
        c.execute("SELECT id, english, oromo FROM phrases WHERE id=? AND status='approved'", (entry_id,))

    row = c.fetchone()
    if not row:
        conn.close()
        return "Entry not found or not approved.", 404

    c.execute("""
        SELECT 1 FROM audio
        WHERE entry_type=? AND entry_id=? AND lang=? AND status='approved'
        LIMIT 1
    """, (entry_type, entry_id, lang))

    already_approved = c.fetchone() is not None
    if already_approved:
        conn.close()
        return "Audio already approved for this entry.", 409

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


# ------------------ ADMIN MANAGEMENT UNLOCK ------------------

@app.route("/admin/manage/unlock", methods=["GET", "POST"])
def admin_manage_unlock():
    if not require_admin():
        return redirect("/admin")

    msg = None
    real_pw = (os.environ.get("ADMIN_MANAGE_PASSWORD") or "").strip()

    if request.method == "POST":
        entered = (request.form.get("manage_password") or "").strip()

        if not real_pw:
            msg = "ADMIN_MANAGE_PASSWORD is not set on the server."
        elif entered == real_pw:
            session["manage_unlocked"] = True
            session.permanent = False
            return redirect("/admin/manage")
        else:
            msg = "Wrong management password."

    return render_template("admin_manage_unlock.html", msg=msg)


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

    if not session.get("manage_unlocked"):
        return redirect("/admin/manage/unlock")

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
                    c.execute(
                        "INSERT INTO admin (email, password) VALUES (?, ?)",
                        (email, generate_password_hash(password))
                    )
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

                c.execute(
                    "INSERT INTO words (english, oromo, status) VALUES (?, ?, 'pending')",
                    (en, om)
                )
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


# ------------------ GADAA AI (FREE DEMO - NO PAID API) ------------------
# URL: /gadaa-ai
# - bilingual Oromo + English
# - rule-based tutor using your own SQLite dictionary
# - promo-friendly, no card required
# - later: can swap backend to paid AI without changing UI

from collections import defaultdict
import time

# Simple in-memory rate limit (per IP). Resets on restart (OK for demo).
_AI_LIMIT_WINDOW_SEC = 60
_AI_LIMIT_MAX_REQ = 20
_ai_hits = defaultdict(list)  # ip -> [timestamps]


def _client_ip():
    # Works behind proxies with ProxyFix
    return (
        request.headers.get("X-Forwarded-For", "").split(",")[0].strip()
        or request.remote_addr
        or "unknown"
    )


def _rate_limit_ok():
    ip = _client_ip()
    now = time.time()
    hits = _ai_hits[ip]
    # keep only last window
    hits = [t for t in hits if now - t < _AI_LIMIT_WINDOW_SEC]
    if len(hits) >= _AI_LIMIT_MAX_REQ:
        _ai_hits[ip] = hits
        return False, ip, len(hits)
    hits.append(now)
    _ai_hits[ip] = hits
    return True, ip, len(hits)


def _db_lookup_word_or_phrase(q: str):
    """
    Try exact match in phrases then words (approved only).
    Returns dict: {"type": "phrase"/"word", "id": int, "english": str, "oromo": str} or None
    """
    clean = normalize_text(q)
    if not clean:
        return None

    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()

    # phrases exact match
    c.execute(
        "SELECT id, english, oromo FROM phrases "
        "WHERE status='approved' AND (english=? OR oromo=?) LIMIT 1",
        (clean, clean),
    )
    r = c.fetchone()
    if r:
        conn.close()
        return {"type": "phrase", "id": r[0], "english": r[1], "oromo": r[2]}

    # word exact match (single token)
    if len(clean.split()) == 1:
        c.execute(
            "SELECT id, english, oromo FROM words "
            "WHERE status='approved' AND (english=? OR oromo=?) LIMIT 1",
            (clean, clean),
        )
        r = c.fetchone()
        if r:
            conn.close()
            return {"type": "word", "id": r[0], "english": r[1], "oromo": r[2]}

    conn.close()
    return None


def _db_suggest(clean: str, limit=6):
    """
    Suggestions from both directions.
    """
    s_en = suggest_terms(clean, "en_om", limit=limit)
    s_om = suggest_terms(clean, "om_en", limit=limit)

    # flatten unique
    items = []
    for k in ("closest", "prefix", "partial"):
        items += s_en.get(k, [])
        items += s_om.get(k, [])

    out = []
    seen = set()
    for x in items:
        if x and x not in seen:
            seen.add(x)
            out.append(x)
        if len(out) >= limit:
            break
    return out


def _make_lesson_card(entry: dict):
    """
    Build a small “teacher style” response.
    """
    en = entry["english"]
    om = entry["oromo"]

    # very lightweight “lesson”
    if entry["type"] == "word":
        examples = [
            f"Example (EN): I use **{en}** in a sentence.",
            f"Example (OM): Ani jecha **{om}** keessatti fayyadama.",
        ]
    else:
        examples = [
            f"Example (EN): **{en}**",
            f"Example (OM): **{om}**",
        ]

    quiz = [
        f"Quick quiz: What is the Oromo for **{en}**?",
        f"Answer: **{om}**",
    ]

    return {
        "title": f"📘 {entry['type'].capitalize()} lesson",
        "english": en,
        "oromo": om,
        "examples": examples,
        "quiz": quiz,
        "audio": get_approved_audio(entry["type"], entry["id"]),  # shows Oromo if exists
    }


@app.route("/gadaa-ai", methods=["GET"])
def gadaa_ai_page():
    trending = get_trending(limit=12)
    return render_template("gadaa_ai.html", trending=trending)


@app.route("/api/gadaa-ai", methods=["POST"])
def gadaa_ai_api():
    ok, ip, count = _rate_limit_ok()
    if not ok:
        return jsonify({
            "ok": False,
            "error": "Too many requests. Please wait 1 minute and try again."
        }), 429

    data = request.get_json(silent=True) or {}
    msg = (data.get("message") or "").strip()
    if not msg:
        return jsonify({"ok": False, "error": "Empty message"}), 400

    clean = normalize_text(msg)

    # basic commands
    if clean in ("help", "what can you do", "menu"):
        return jsonify({
            "ok": True,
            "reply": {
                "type": "text",
                "text": (
                    "Hi! I’m **Gadaa AI (free demo)**.\n\n"
                    "Try:\n"
                    "- Type a word/phrase in Oromo or English (exact match)\n"
                    "- Ask: `quiz me` or `lesson`\n"
                    "- Ask: `suggest <word>`\n\n"
                    "Note: This demo uses your dictionary database (no paid AI yet)."
                )
            }
        })

    if clean.startswith("suggest "):
        term = clean.replace("suggest ", "", 1).strip()
        sug = _db_suggest(term, limit=8) if term else []
        if not sug:
            text = "No suggestions found."
        else:
            text = "Suggestions: " + ", ".join(sug)
        return jsonify({"ok": True, "reply": {"type": "text", "text": text}})

    # "quiz me" -> use a trending query if exists, else generic
    if clean in ("quiz me", "quiz", "test me"):
        trending = get_trending(limit=1)
        pick = trending[0][0] if trending else "hello"
        entry = _db_lookup_word_or_phrase(pick) or _db_lookup_word_or_phrase("hello")
        if entry:
            card = _make_lesson_card(entry)
            return jsonify({"ok": True, "reply": {"type": "card", "card": card}})
        return jsonify({
            "ok": True,
            "reply": {"type": "text", "text": "I need more approved words/phrases to quiz you."}
        })

    # Normal: try dictionary lookup
    entry = _db_lookup_word_or_phrase(msg)
    if entry:
        card = _make_lesson_card(entry)
        return jsonify({"ok": True, "reply": {"type": "card", "card": card}})

    # Not found: suggestions
    sug = _db_suggest(clean, limit=8) if clean else []
    if sug:
        return jsonify({
            "ok": True,
            "reply": {
                "type": "text",
                "text": "I couldn't find an exact match. Try one of these: " + ", ".join(sug)
            }
        })

    return jsonify({
        "ok": True,
        "reply": {
            "type": "text",
            "text": (
                "I couldn't find that in the dictionary yet.\n"
                "Tip: try a simpler word, or submit it via **Submit Word / Submit Phrase**."
            )
        }
    })


# ------------------ RUN / MIGRATE ------------------

if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1 and sys.argv[1] == "migrate":
        ensure_key_columns()
        backfill_keys()
        ensure_key_indexes()
        print("DB migration done")
        sys.exit(0)   # ✅ VERY IMPORTANT → stop here

    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)


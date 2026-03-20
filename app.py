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
from urllib.parse import quote, unquote
import unicodedata

import requests
from flask import (
    Flask, render_template, request, redirect, session,
    jsonify, send_from_directory, abort, make_response, Response
)
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from werkzeug.middleware.proxy_fix import ProxyFix
from openpyxl import load_workbook

# ------------------ APP SETUP ------------------

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "dev")

from datetime import timedelta

# True i produksjon/https (Render + Cloudflare). False lokalt pÃ¥ http.
IS_PROD = (os.environ.get("FLASK_ENV") == "production") or bool(os.environ.get("RENDER"))

app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=IS_PROD,
    PERMANENT_SESSION_LIFETIME=timedelta(hours=12),
)

# âœ… IMPORTANT for Render / reverse proxy: makes Flask understand HTTPS + correct host
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
app.logger.info(f"âœ… Using DB_NAME={DB_NAME}")

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
    max_word_urls = 50000
    urls = [
        ("/", "daily", "1.0"),
        ("/dictionary", "daily", "0.9"),
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
    static_url_count = len(urls)
    emitted_word_urls = 0
    fetched_word_rows = 0
    for path, freq, prio in urls:
        loc = f"{base}{path}"
        xml_parts.append("<url>")
        xml_parts.append(f"<loc>{loc}</loc>")
        xml_parts.append(f"<lastmod>{now}</lastmod>")
        xml_parts.append(f"<changefreq>{freq}</changefreq>")
        xml_parts.append(f"<priority>{prio}</priority>")
        xml_parts.append("</url>")

    # --- WORD URLS ---
    try:
        conn = sqlite3.connect(DB_NAME)
        c = conn.cursor()
        c.execute("""
            SELECT DISTINCT TRIM(english)
            FROM words
            WHERE status='approved'
            AND english IS NOT NULL
            AND TRIM(english) != ''
            LIMIT 50000
        """)
        rows = c.fetchall()
        fetched_word_rows = len(rows)

        for (en,) in rows:
            try:
                url = f"{base}/word/{quote(en, safe='')}"
                xml_parts.append(f"""
    <url>
        <loc>{url}</loc>
        <changefreq>weekly</changefreq>
        <priority>0.8</priority>
    </url>
""")
                emitted_word_urls += 1
            except Exception as e:
                print("skip bad word:", en, e)

    except Exception as e:
        print("sitemap word error:", e)
    finally:
        try:
            conn.close()
        except Exception:
            pass

    xml_parts.append("</urlset>")
    final_total_urls = static_url_count + emitted_word_urls
    sitemap_log_line = (
        f"sitemap_xml db_path={DB_NAME} "
        f"fetched_word_rows={fetched_word_rows} "
        f"final_total_urls={final_total_urls}"
    )
    app.logger.info(sitemap_log_line)
    logging.getLogger("gunicorn.error").info(sitemap_log_line)

    xml = "".join(xml_parts)
    return Response(xml, mimetype="application/xml")


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

IMPORT_BATCH_SIZE = 100
IMPORT_MAX_WORDS = 200
IMPORT_MAX_CALLS = max(1, (IMPORT_MAX_WORDS + IMPORT_BATCH_SIZE - 1) // IMPORT_BATCH_SIZE)


# ------------------ STOPWORDS ------------------

OROMO_STOP = {"fi", "kan", "inni", "isaan", "ani", "ati", "nu", "keessa", "irratti"}
EN_STOP = {"the", "is", "are", "to", "and", "of", "in", "on", "a", "an", "for", "with", "it", "this"}

# ------------------ TEXT NORMALIZATION ------------------

def normalize_text(text: str) -> str:
    t = (text or "").strip()
    t = t.replace("â€™", "'").replace("â€˜", "'").replace("`", "'")
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
    t = t.replace("â€™", "'").replace("â€˜", "'").replace("`", "'")
    t = unicodedata.normalize("NFKC", t)
    t = t.casefold()
    t = re.sub(r"\s+", " ", t).strip()
    return t


# ------------------ COMMUNITY FILE PARSERS (NO GOOGLE) ------------------

def parse_csv_pairs_from_path(path: str):
    # prÃ¸v UTF-8 fÃ¸rst, fallback latin-1
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

def parse_txt_english_rows(file_bytes: bytes):
    text = file_bytes.decode("utf-8", errors="replace")
    return [line for line in text.splitlines()]


def parse_csv_english_rows(file_bytes: bytes):
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
        words.append(str(raw or ""))

    return words


def parse_xlsx_english_rows(file_bytes: bytes):
    wb = load_workbook(BytesIO(file_bytes))
    ws = wb.active

    words = []
    for idx, row in enumerate(ws.iter_rows(values_only=True)):
        if not row:
            words.append("")
            continue
        a = (row[0] if len(row) > 0 else "") or ""

        if idx == 0 and str(a).strip().lower() in ("english", "en"):
            continue

        words.append(str(a))

    return words


def parse_txt_english(file_bytes: bytes):
    words = [normalize_text(x) for x in parse_txt_english_rows(file_bytes)]
    return dedup_preserve_order([w for w in words if w])


def parse_csv_english(file_bytes: bytes):
    words = [normalize_text(x) for x in parse_csv_english_rows(file_bytes)]
    return dedup_preserve_order([w for w in words if w])


def parse_xlsx_english(file_bytes: bytes):
    words = [normalize_text(x) for x in parse_xlsx_english_rows(file_bytes)]
    return dedup_preserve_order([w for w in words if w])


# ------------------ ADMIN + RECORDER HELPERS ------------------

def require_admin() -> bool:
    return "admin" in session


def _admin_id() -> int:
    try:
        return int(session.get("admin"))
    except Exception:
        return 0


# âœ… recorder session (password-based)
def require_recorder() -> bool:
    return bool(session.get("recorder") == 1)


def _words_table_counts():
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    out = {
        "total_rows": 0,
        "non_empty_english_rows": 0,
        "approved_rows": 0,
        "approved_non_empty_english_rows": 0,
        "distinct_approved_non_empty_english_rows": 0,
    }

    c.execute("SELECT COUNT(*) FROM words")
    out["total_rows"] = int((c.fetchone() or [0])[0] or 0)

    c.execute("SELECT COUNT(*) FROM words WHERE english IS NOT NULL AND TRIM(english) != ''")
    out["non_empty_english_rows"] = int((c.fetchone() or [0])[0] or 0)

    c.execute("SELECT COUNT(*) FROM words WHERE status='approved'")
    out["approved_rows"] = int((c.fetchone() or [0])[0] or 0)

    c.execute("""
        SELECT COUNT(*)
        FROM words
        WHERE status='approved' AND english IS NOT NULL AND TRIM(english) != ''
    """)
    out["approved_non_empty_english_rows"] = int((c.fetchone() or [0])[0] or 0)

    c.execute("""
        SELECT COUNT(*)
        FROM (
            SELECT DISTINCT TRIM(english) AS english
            FROM words
            WHERE status='approved' AND english IS NOT NULL AND TRIM(english) != ''
        )
    """)
    out["distinct_approved_non_empty_english_rows"] = int((c.fetchone() or [0])[0] or 0)

    conn.close()
    return out


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

# ------------------ MULTILINGUAL TRANSLATION CONFIG ------------------

LANGUAGE_OPTIONS = {
    "om": {"label": "Oromo", "google_code": "om", "speech_code": "om-ET", "rtl": False},
    "en": {"label": "English", "google_code": "en", "speech_code": "en-US", "rtl": False},
    "am": {"label": "Amharic", "google_code": "am", "speech_code": "am-ET", "rtl": False},
    "ar": {"label": "Arabic", "google_code": "ar", "speech_code": "ar-SA", "rtl": True},
    "fr": {"label": "French", "google_code": "fr", "speech_code": "fr-FR", "rtl": False},
    "zh-CN": {"label": "Chinese", "google_code": "zh-CN", "speech_code": "zh-CN", "rtl": False},
}
EXTRA_GENERATED_LANGS = ("am", "ar", "zh-CN", "fr")

def _is_supported_lang(lang_code: str) -> bool:
    return lang_code in LANGUAGE_OPTIONS


def _google_lang_code(lang_code: str) -> str:
    cfg = LANGUAGE_OPTIONS.get(lang_code, {})
    return cfg.get("google_code", lang_code)


def _speech_lang_code(lang_code: str) -> str:
    cfg = LANGUAGE_OPTIONS.get(lang_code, {})
    return cfg.get("speech_code", "en-US")


def _is_rtl_lang(lang_code: str) -> bool:
    cfg = LANGUAGE_OPTIONS.get(lang_code, {})
    return bool(cfg.get("rtl"))


def _upsert_pending_word_base(conn, english_text: str, oromo_text: str, status: str = "pending"):
    """
    Insert a pending base word or safely complete an existing partial row.
    Returns: (word_id, inserted_new, repaired_existing_partial)
    """
    en = normalize_text(english_text or "")
    om = normalize_text(oromo_text or "")
    en_key = make_search_key(_strip_edge_punct(en))
    om_key = make_search_key(_strip_edge_punct(om))

    if not en or not om or not en_key or not om_key:
        return None, False, False

    c = conn.cursor()
    c.execute("""
        SELECT id, english, oromo
        FROM words
        WHERE english_key=? OR oromo_key=? OR english=? OR oromo=?
        LIMIT 1
    """, (en_key, om_key, en, om))
    row = c.fetchone()

    if row:
        wid, existing_en, existing_om = row
        existing_en_norm = normalize_text(existing_en or "")
        existing_om_norm = normalize_text(existing_om or "")

        merged_en = existing_en_norm or en
        merged_om = existing_om_norm or om
        merged_en_key = make_search_key(_strip_edge_punct(merged_en))
        merged_om_key = make_search_key(_strip_edge_punct(merged_om))

        repaired = (merged_en != existing_en_norm) or (merged_om != existing_om_norm)
        if repaired:
            c.execute(
                "UPDATE words SET english=?, oromo=?, english_key=?, oromo_key=? WHERE id=?",
                (merged_en, merged_om, merged_en_key, merged_om_key, wid),
            )
        return wid, False, repaired

    safe_status = status if status in ("pending", "approved") else "pending"
    c.execute(
        "INSERT INTO words (english, oromo, english_key, oromo_key, status) VALUES (?, ?, ?, ?, ?)",
        (en, om, en_key, om_key, safe_status),
    )
    return c.lastrowid, True, False


def _cache_extra_translations_for_words(word_items):
    """
    Best-effort cache warmup for extra languages.
    word_items: list[(word_id, english_text)]
    """
    if not word_items:
        return 0

    cached_count = 0

    for lang in EXTRA_GENERATED_LANGS:
        try:
            missing_ids = []
            missing_english = []

            for wid, en in word_items:
                if not wid or not en:
                    continue
                cached = _get_cached_generated_translation(wid, lang)
                if cached and normalize_text(cached[0] or ""):
                    continue
                missing_ids.append(wid)
                missing_english.append(en)

            if not missing_english:
                continue

            translated_list = google_translate_batch_v2(
                missing_english,
                target=_google_lang_code(lang),
                source="en",
            )
            if not translated_list or len(translated_list) != len(missing_english):
                continue

            for wid, translated in zip(missing_ids, translated_list):
                translated_text = normalize_text(translated or "")
                if not translated_text:
                    continue
                _save_generated_translation(
                    wid,
                    lang,
                    translated_text,
                    provider="google_translate_v2",
                    tts_audio_url=None,
                )
                cached_count += 1
        except Exception as e:
            app.logger.exception(f"extra translation cache warmup failed for lang={lang}: {repr(e)}")
            continue

    return cached_count


def google_translate_text_v2(text: str, target: str, source: str = "en") -> str:
    t = normalize_text(text)
    if not t:
        return ""
    out = google_translate_batch_v2([t], target=target, source=source)
    if not out:
        return ""
    return normalize_text(out[0] or "")


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
    return re.sub(r"^[\s\"'â€œâ€â€˜â€™`]+|[.!?,;:\s\"'â€œâ€â€˜â€™`]+$", "", s or "").strip()


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


def ensure_generated_translations_table():
    try:
        conn = sqlite3.connect(DB_NAME)
        c = conn.cursor()

        c.execute("""
        CREATE TABLE IF NOT EXISTS generated_translations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            word_id INTEGER NOT NULL,
            lang_code TEXT NOT NULL,
            translated_text TEXT NOT NULL,
            provider TEXT NOT NULL DEFAULT 'google_translate_v2',
            tts_audio_url TEXT,
            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(word_id, lang_code)
        )
        """)

        c.execute("CREATE INDEX IF NOT EXISTS idx_generated_translations_word_id ON generated_translations(word_id)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_generated_translations_lang_code ON generated_translations(lang_code)")

        conn.commit()
        conn.close()
        return True
    except Exception as e:
        app.logger.exception(f"Failed to ensure generated_translations table: {repr(e)}")
        return False


# Run DB init + migrations at startup
init_db()
ensure_key_columns()
backfill_keys()
ensure_key_indexes()
_generated_table_ready = ensure_generated_translations_table()


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


def _get_cached_generated_translation(word_id: int, lang_code: str):
    try:
        conn = sqlite3.connect(DB_NAME)
        c = conn.cursor()
        c.execute("""
            SELECT translated_text, tts_audio_url
            FROM generated_translations
            WHERE word_id=? AND lang_code=?
            LIMIT 1
        """, (word_id, lang_code))
        row = c.fetchone()
        conn.close()
        return row
    except Exception as e:
        if "no such table: generated_translations" in str(e).lower():
            ensure_generated_translations_table()
        app.logger.exception(f"generated_translations cache read failed: {repr(e)}")
        return None


def _save_generated_translation(
    word_id: int,
    lang_code: str,
    translated_text: str,
    provider: str = "google_translate_v2",
    tts_audio_url: str = None
):
    if not translated_text:
        return
    try:
        conn = sqlite3.connect(DB_NAME)
        c = conn.cursor()
        c.execute("""
            INSERT INTO generated_translations
            (word_id, lang_code, translated_text, provider, tts_audio_url, updated_at)
            VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(word_id, lang_code) DO UPDATE SET
                translated_text=excluded.translated_text,
                provider=excluded.provider,
                tts_audio_url=excluded.tts_audio_url,
                updated_at=CURRENT_TIMESTAMP
        """, (word_id, lang_code, translated_text, provider, tts_audio_url))
        conn.commit()
        conn.close()
    except Exception as e:
        if "no such table: generated_translations" in str(e).lower():
            if ensure_generated_translations_table():
                try:
                    conn = sqlite3.connect(DB_NAME)
                    c = conn.cursor()
                    c.execute("""
                        INSERT INTO generated_translations
                        (word_id, lang_code, translated_text, provider, tts_audio_url, updated_at)
                        VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                        ON CONFLICT(word_id, lang_code) DO UPDATE SET
                            translated_text=excluded.translated_text,
                            provider=excluded.provider,
                            tts_audio_url=excluded.tts_audio_url,
                            updated_at=CURRENT_TIMESTAMP
                    """, (word_id, lang_code, translated_text, provider, tts_audio_url))
                    conn.commit()
                    conn.close()
                    return
                except Exception as e2:
                    app.logger.exception(f"generated_translations retry write failed: {repr(e2)}")
        app.logger.exception(f"generated_translations cache write failed: {repr(e)}")


def clear_generated_translations_for_word(word_id: int):
    try:
        conn = sqlite3.connect(DB_NAME)
        c = conn.cursor()
        c.execute("DELETE FROM generated_translations WHERE word_id=?", (word_id,))
        conn.commit()
        conn.close()
    except Exception as e:
        app.logger.exception(f"generated_translations cache clear failed: {repr(e)}")


def _get_word_by_key(source_lang: str, key_text: str):
    if source_lang not in ("om", "en"):
        return None
    col = "oromo_key" if source_lang == "om" else "english_key"
    try:
        conn = sqlite3.connect(DB_NAME)
        c = conn.cursor()
        c.execute(f"""
            SELECT id, english, oromo
            FROM words
            WHERE status='approved' AND {col}=?
            LIMIT 1
        """, (key_text,))
        row = c.fetchone()
        conn.close()
        return row
    except Exception as e:
        app.logger.exception(f"base word lookup failed ({source_lang}): {repr(e)}")
        return None


def _get_word_by_any_key(key_text: str):
    """Legacy-compatible base lookup: match either English or Oromo key."""
    if not key_text:
        return None
    try:
        conn = sqlite3.connect(DB_NAME)
        c = conn.cursor()
        c.execute("""
            SELECT id, english, oromo
            FROM words
            WHERE status='approved' AND (english_key=? OR oromo_key=?)
            LIMIT 1
        """, (key_text, key_text))
        row = c.fetchone()
        conn.close()
        return row
    except Exception as e:
        app.logger.exception(f"base word fallback lookup failed: {repr(e)}")
        return None


def _auto_translate_from_english(english_text: str, target_lang: str) -> str:
    if target_lang == "en":
        return normalize_text(english_text)
    return google_translate_text_v2(
        english_text,
        target=_google_lang_code(target_lang),
        source="en"
    )


def _get_or_generate_word_translation(word_id: int, english_text: str, target_lang: str):
    cached = _get_cached_generated_translation(word_id, target_lang)
    if cached and normalize_text(cached[0] or ""):
        return normalize_text(cached[0]), cached[1], True

    translated = _auto_translate_from_english(english_text, target_lang)
    if not translated:
        return "", None, False

    # TODO: server-side TTS generation can populate tts_audio_url later.
    _save_generated_translation(word_id, target_lang, translated, provider="google_translate_v2", tts_audio_url=None)
    return translated, None, False


def safe_translate_multilingual(text: str, source_lang: str, target_lang: str):
    try:
        return translate_multilingual(text, source_lang, target_lang)
    except Exception as e:
        app.logger.exception(f"translate_multilingual failed: {repr(e)}")
        return {
            "text": "",
            "is_exact": 0,
            "is_phrase": 0,
            "is_auto_translation": (target_lang not in ("om", "en") or source_lang not in ("om", "en")),
            "tts_audio_url": None
        }


def _dictionary_lookup_result(query_text: str, source_lang: str, target_lang: str):
    q = normalize_text(query_text)
    if not q:
        return None, None, None, False

    base_row = None
    pivot_english = None

    if source_lang in ("om", "en"):
        wkey = make_search_key(_strip_edge_punct(q))
        if wkey:
            base_row = _get_word_by_key(source_lang, wkey)
            # Keep old dictionary behavior: if selected source misses, still try either side.
            if not base_row:
                base_row = _get_word_by_any_key(wkey)
    else:
        pivot_english = google_translate_text_v2(
            q,
            target="en",
            source=_google_lang_code(source_lang)
        )
        if pivot_english:
            wkey = make_search_key(_strip_edge_punct(pivot_english))
            if wkey:
                base_row = _get_word_by_key("en", wkey)

    if base_row:
        wid, en, om = base_row
        target_text = ""
        tts_audio_url = None
        is_auto = False
        auto_unavailable = False

        if target_lang == "en":
            target_text = en
        elif target_lang == "om":
            target_text = om
        else:
            try:
                target_text, tts_audio_url, _ = _get_or_generate_word_translation(wid, en, target_lang)
            except Exception as e:
                app.logger.exception(f"dictionary auto translation failed: {repr(e)}")
                target_text = ""
                tts_audio_url = None

            if not target_text:
                # Retry direct provider path before final fallback.
                tr_retry = safe_translate_multilingual(en, "en", target_lang)
                target_text = (tr_retry or {}).get("text", "") or ""
                if target_text:
                    try:
                        _save_generated_translation(
                            wid, target_lang, target_text,
                            provider="google_translate_v2", tts_audio_url=None
                        )
                    except Exception:
                        pass

            if not target_text:
                # Final fallback keeps page functional if provider is down.
                target_text = en
                auto_unavailable = True
            is_auto = True

        if source_lang == "en":
            source_text = en
        elif source_lang == "om":
            source_text = om
        else:
            source_text = q

        result = {
            "source_text": source_text,
            "target_text": target_text,
            "english": en,
            "oromo": om,
            "is_auto_translation": is_auto,
            "auto_unavailable": auto_unavailable,
            "tts_audio_url": tts_audio_url
        }
        return result, wid, None, True

    # Base entry not found: do not return generated result as primary dictionary output.
    return None, None, None, False


def get_or_generate_extra_translations(word_id: int, english_text: str):
    """
    Fetch or generate all configured extra-language translations for a base word.
    Failures per language are isolated so one provider/cache error does not break the page.
    """
    out = {}
    if not word_id or not english_text:
        return out

    for lang in EXTRA_GENERATED_LANGS:
        try:
            translated, tts_url, _ = _get_or_generate_word_translation(word_id, english_text, lang)
            if translated:
                out[lang] = {
                    "text": translated,
                    "tts_audio_url": tts_url
                }
        except Exception as e:
            app.logger.exception(f"extra translation failed for lang={lang}, word_id={word_id}: {repr(e)}")
            continue

    return out


def translate_multilingual(text: str, source_lang: str, target_lang: str):
    t = normalize_text(text)
    if not t:
        return {"text": "", "is_exact": 0, "is_phrase": 0, "is_auto_translation": False, "tts_audio_url": None}

    if source_lang == target_lang:
        return {"text": t, "is_exact": 1, "is_phrase": 0, "is_auto_translation": False, "tts_audio_url": None}

    if source_lang == "om":
        english_text, is_exact, is_phrase = translate_multipart_text(t, "om_en")
        english_text = normalize_text(english_text)
        if target_lang == "en":
            return {"text": english_text, "is_exact": is_exact, "is_phrase": is_phrase, "is_auto_translation": False, "tts_audio_url": None}

        tokens = t.split()
        if len(tokens) == 1:
            row = _get_word_by_key("om", make_search_key(_strip_edge_punct(tokens[0])))
            if row:
                translated, tts_url, _ = _get_or_generate_word_translation(row[0], row[1], target_lang)
                if translated:
                    return {"text": translated, "is_exact": 1, "is_phrase": 0, "is_auto_translation": True, "tts_audio_url": tts_url}

        translated = _auto_translate_from_english(english_text, target_lang) if english_text else ""
        return {"text": translated, "is_exact": is_exact, "is_phrase": is_phrase, "is_auto_translation": bool(translated), "tts_audio_url": None}

    if source_lang == "en":
        if target_lang == "om":
            out, is_exact, is_phrase = translate_multipart_text(t, "en_om")
            return {"text": out, "is_exact": is_exact, "is_phrase": is_phrase, "is_auto_translation": False, "tts_audio_url": None}

        tokens = t.split()
        if len(tokens) == 1:
            row = _get_word_by_key("en", make_search_key(_strip_edge_punct(tokens[0])))
            if row:
                translated, tts_url, _ = _get_or_generate_word_translation(row[0], row[1], target_lang)
                if translated:
                    return {"text": translated, "is_exact": 1, "is_phrase": 0, "is_auto_translation": True, "tts_audio_url": tts_url}

        translated = _auto_translate_from_english(t, target_lang)
        return {"text": translated, "is_exact": 0, "is_phrase": 0, "is_auto_translation": bool(translated), "tts_audio_url": None}

    # Non-base source languages always pivot through English.
    src_google = _google_lang_code(source_lang)
    source_to_english = google_translate_text_v2(t, target="en", source=src_google)
    if not source_to_english:
        return {"text": "", "is_exact": 0, "is_phrase": 0, "is_auto_translation": True, "tts_audio_url": None}

    if target_lang == "en":
        return {"text": source_to_english, "is_exact": 0, "is_phrase": 0, "is_auto_translation": True, "tts_audio_url": None}

    if target_lang == "om":
        out, is_exact, is_phrase = translate_multipart_text(source_to_english, "en_om")
        return {"text": out, "is_exact": is_exact, "is_phrase": is_phrase, "is_auto_translation": True, "tts_audio_url": None}

    out = _auto_translate_from_english(source_to_english, target_lang)
    return {"text": out, "is_exact": 0, "is_phrase": 0, "is_auto_translation": True, "tts_audio_url": None}


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

def suggest_phrases_from_text(text: str, direction: str, limit: int = 8, min_words: int = 2, max_words: int = 6):
    """
    Suggest approved phrases found inside the user's text using phrase_aliases.
    Returns a list of dicts:
      { "phrase_id": int, "source_text": str, "english": str, "oromo": str, "matched_ngram": str }
    direction:
      - 'en_om' means user typed English, target Oromo
      - 'om_en' means user typed Oromo, target English
    """
    parts = split_segments(text)
    if not parts:
        return []

    # Extract segments, normalize, split to words
    segments_words = []
    for seg_text, _, _ in parts:
        seg = normalize_text(seg_text)
        if not seg:
            continue
        words = seg.split()
        if words:
            segments_words.append(words)

    if not segments_words:
        return []

    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()

    # For scoring and de-dup
    best_by_phrase_id = {}  # phrase_id -> (score, payload)

    # Decide which alias column to search
    alias_col = "english_alias_key" if direction == "en_om" else "oromo_alias_key"

    # We will do lookups for each n-gram key.
    # To keep it efficient, we can cache alias lookups in a dict
    alias_cache = {}  # key -> row

    for words in segments_words:
        n = len(words)
        for i in range(n):
            for L in range(max_words, min_words - 1, -1):
                if i + L > n:
                    continue
                ngram = " ".join(words[i:i+L])
                k = key_for(ngram)
                if not k:
                    continue

                # Cache DB lookups for speed
                if k in alias_cache:
                    row = alias_cache[k]
                else:
                    row = c.execute(f"""
                        SELECT a.phrase_id, p.english, p.oromo
                        FROM phrase_aliases a
                        JOIN phrases p ON p.id = a.phrase_id
                        WHERE p.status='approved' AND a.{alias_col}=? 
                        LIMIT 1
                    """, (k,)).fetchone()
                    alias_cache[k] = row

                if not row:
                    continue

                phrase_id, en, om = row
                # Score: prefer longer phrase, earlier in sentence
                score = (L * 1000) - i

                payload = {
                    "phrase_id": phrase_id,
                    "source_text": ngram,
                    "matched_ngram": ngram,
                    "english": en,
                    "oromo": om,
                }

                prev = best_by_phrase_id.get(phrase_id)
                if (prev is None) or (score > prev[0]):
                    best_by_phrase_id[phrase_id] = (score, payload)

    conn.close()

    # Sort by score descending
    suggestions = [v[1] for v in best_by_phrase_id.values()]
    suggestions.sort(key=lambda d: (
        -len(normalize_text(d["matched_ngram"]).split()),
        -len(normalize_text(d["matched_ngram"])),
        d["matched_ngram"].lower()
    ))

    return suggestions[:limit]
EN_DROP_WORDS = {"the", "a", "an"}         # safe to drop in Oromo output
EN_SOFT_WORDS = {"please"}                # optional: skip in fallback if not part of a matched phrase

def postprocess_segment(text_out: str, direction: str) -> str:
    s = (text_out or "").strip()
    s = re.sub(r"\s+", " ", s).strip()
    s = re.sub(r"\s+([?.!,;:])", r"\1", s)        # no space before punctuation
    s = re.sub(r"([?.!,;:])\1+", r"\1", s)        # collapse repeated punctuation
    if direction == "en_om":
        # remove any leftover English articles that slipped through
        s = re.sub(r"\b(the|a|an)\b", "", s, flags=re.I)
        s = re.sub(r"\s+", " ", s).strip()
        s = re.sub(r"\s+([?.!,;:])", r"\1", s)
    return s
def apply_grammar_templates(output_text: str, direction: str) -> str:
    if direction != "en_om":
        return output_text

    s = normalize_text(output_text)

    # Clean common artifacts from word fallback
    s = re.sub(r"\bthe\b", "", s, flags=re.I)
    s = re.sub(r"\s+", " ", s).strip()

    # Fix spacing before punctuation
    s = re.sub(r"\s+([?.!,;:])", r"\1", s)

    return s


def try_simple_sov_reorder(text: str, direction: str) -> str:
    if direction != "en_om":
        return text

    words = text.split()
    if len(words) != 3:
        return text

    subj, verb, obj = words

    # simple Oromo pronoun subjects
    if subj.casefold() in {"ani", "ati", "inni", "isheen", "nuti", "isin"}:
        return f"{subj} {obj} {verb}"

    return text
EN_OM_TEMPLATES = [
    # can you (please) show me the way
    (
        re.compile(r"^(please\s+)?can\s+you\s+show\s+me\s+the\s+way\??$", re.I),
        "Karaa natti agarsiisuu dandeessaa?"
    ),

    (
        re.compile(r"^(please\s+)?can\s+you\s+show\s+me\s+the\s+way\?$", re.I),
        "Karaa natti agarsiisuu dandeessaa?"
    ),
]



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

# ------------------ DICTIONARY ------------------

@app.route("/dictionary", methods=["GET", "POST"])
def dictionary():
    result = None
    result_id = None
    suggestions = None
    audio = None
    source_lang = "om"
    target_lang = "en"
    is_auto_translation = False
    tts_audio_url = None
    lookup_error = None
    other_translations = {}

    # --- GET search (?q=) ---
    q = request.args.get("q", "").strip()
    source_lang = (request.args.get("source_lang") or source_lang).strip()
    target_lang = (request.args.get("target_lang") or target_lang).strip()

    # --- POST search (fallback hvis form bruker POST) ---
    if request.method == "POST":
        q = (request.form.get("q") or request.form.get("word") or "").strip()
        source_lang = (request.form.get("source_lang") or source_lang).strip()
        target_lang = (request.form.get("target_lang") or target_lang).strip()

    if not _is_supported_lang(source_lang):
        source_lang = "om"
    if not _is_supported_lang(target_lang):
        target_lang = "en"
    if source_lang == target_lang:
        target_lang = "en" if source_lang != "en" else "om"

    if q:
        try:
            result, result_id, lookup_error, from_base = _dictionary_lookup_result(q, source_lang, target_lang)
            is_auto_translation = bool(result and result.get("is_auto_translation"))
            tts_audio_url = result.get("tts_audio_url") if result else None
            if result and result.get("auto_unavailable"):
                lookup_error = "Auto translation unavailable. Showing base Oromo-English result."

            if result_id:
                audio = get_approved_audio("word", result_id)
                try:
                    other_translations = get_or_generate_extra_translations(result_id, result.get("english", ""))
                except Exception as e:
                    app.logger.exception(f"/dictionary extra translations failed: {repr(e)}")
                    other_translations = {}

            if (not from_base) and source_lang in ("om", "en"):
                word = make_search_key(q)
                suggestions = {
                    "en": suggest_terms(word, "en_om"),
                    "om": suggest_terms(word, "om_en")
                }
                if result is None:
                    # Trigger template "no result found" block safely.
                    result = {}
        except Exception as e:
            app.logger.exception(f"/dictionary lookup failed: {repr(e)}")
            lookup_error = "Translation is temporarily unavailable. Showing base dictionary data."
            result = {
                "source_text": q,
                "target_text": "",
                "english": "",
                "oromo": "",
                "is_auto_translation": False,
                "tts_audio_url": None
            }

    # full dictionary list (load after lookup work so on-use cache writes are
    # not competing with this route-level DB handle)
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("""
            SELECT id, english, oromo
            FROM words
            WHERE status='approved'
            ORDER BY english ASC
        """)
    all_words = c.fetchall()
    list_other_translations = {}

    try:
        placeholders = ",".join("?" for _ in EXTRA_GENERATED_LANGS)
        c.execute(
            f"""
            SELECT gt.word_id, gt.lang_code, gt.translated_text
            FROM generated_translations gt
            JOIN words w ON w.id = gt.word_id
            WHERE w.status='approved'
              AND gt.lang_code IN ({placeholders})
              AND gt.translated_text IS NOT NULL
              AND TRIM(gt.translated_text) != ''
            """,
            EXTRA_GENERATED_LANGS,
        )
        for wid, lang_code, translated_text in c.fetchall():
            wid_int = int(wid or 0)
            txt = normalize_text(translated_text or "")
            if not wid_int or not txt:
                continue
            row = list_other_translations.setdefault(wid_int, {})
            row[lang_code] = txt
    except Exception as e:
        app.logger.exception(f"/dictionary list extra translations failed: {repr(e)}")
        list_other_translations = {}

    conn.close()

    trending = get_trending(limit=15)
    approved_oromo_audio_word_ids = get_approved_oromo_audio_ids("word")

    return render_template(
        "dictionary.html",
        q=q,
        result=result,
        result_id=result_id,
        source_lang=source_lang,
        target_lang=target_lang,
        language_options=LANGUAGE_OPTIONS,
        result_is_rtl=_is_rtl_lang(target_lang),
        source_speech_lang=_speech_lang_code(source_lang),
        target_speech_lang=_speech_lang_code(target_lang),
        is_auto_translation=is_auto_translation,
        tts_audio_url=tts_audio_url,
        lookup_error=lookup_error,
        other_translations=other_translations,
        list_other_translations=list_other_translations,
        audio=audio,
        words=all_words,
        suggestions=suggestions,
        trending=trending,
        approved_oromo_audio_word_ids=approved_oromo_audio_word_ids
    )


@app.route("/word/<path:term>", methods=["GET"])
def word_detail(term):
    raw = normalize_text(unquote(term or ""))
    key = make_search_key(_strip_edge_punct(raw))
    if not key:
        abort(404)

    try:
        conn = sqlite3.connect(DB_NAME)
        c = conn.cursor()
        c.execute("""
            SELECT id, english, oromo
            FROM words
            WHERE status='approved' AND (english_key=? OR oromo_key=?)
            LIMIT 1
        """, (key, key))
        row = c.fetchone()
        conn.close()
    except Exception as e:
        app.logger.exception(f"/word lookup failed: {repr(e)}")
        row = None

    if not row:
        abort(404)

    wid, en, om = row
    audio = get_approved_audio("word", wid)

    word = {
        "en": en,
        "om": om,
        "explanation": "",
        "audio_oromo": audio.get("oromo", ""),
        "audio_english": audio.get("english", "")
    }

    other_translations = {}
    try:
        other_translations = get_or_generate_extra_translations(wid, en)
    except Exception as e:
        app.logger.exception(f"/word extra translations failed: {repr(e)}")

    return render_template(
        "words.html",
        word=word,
        other_translations=other_translations,
        current_year=datetime.utcnow().year
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


def find_exact_base_match(text: str, source_lang: str):
    if source_lang not in ("om", "en"):
        return None, None

    clean_exact = normalize_text(text)
    key_candidates = build_key_candidates(text)
    phrase_col = "oromo_key" if source_lang == "om" else "english_key"
    word_col = "oromo_key" if source_lang == "om" else "english_key"

    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()

    matched = None
    audio = None

    if key_candidates:
        for k in key_candidates:
            pr = c.execute(
                f"SELECT id FROM phrases WHERE status='approved' AND {phrase_col}=? LIMIT 1",
                (k,)
            ).fetchone()
            if pr:
                matched = {"type": "phrase", "id": pr[0]}
                audio = get_approved_audio("phrase", pr[0])
                break

    if not matched:
        tokens = [t for t in _TOKEN_RE.findall(clean_exact) if not t.isspace()]
        word_tokens = [t for t in tokens if re.fullmatch(r"[\w']+", t)]
        if len(word_tokens) == 1 and len([t for t in tokens if re.fullmatch(r"[\w']+", t)]) == 1:
            wkey = make_search_key(word_tokens[0])
            if wkey:
                wr = c.execute(
                    f"SELECT id FROM words WHERE status='approved' AND {word_col}=? LIMIT 1",
                    (wkey,)
                ).fetchone()
                if wr:
                    matched = {"type": "word", "id": wr[0]}
                    audio = get_approved_audio("word", wr[0])

    conn.close()
    return matched, audio


@app.route("/translate", methods=["GET", "POST"])
def translate():
    result = None
    text = ""
    direction = "om_en"
    source_lang = "om"
    target_lang = "en"
    suggestions = None
    audio = None
    matched = None
    phrase_suggestions = None
    is_auto_translation = False
    tts_audio_url = None
    translate_error = None

    if request.method == "POST":
        text = request.form.get("text", "")
        source_lang = (request.form.get("source_lang") or "").strip()
        target_lang = (request.form.get("target_lang") or "").strip()
        legacy_direction = (request.form.get("direction") or "").strip()

        # Backward compatibility for old form payloads
        if not source_lang or not target_lang:
            if legacy_direction == "om_en":
                source_lang, target_lang = "om", "en"
            elif legacy_direction == "en_om":
                source_lang, target_lang = "en", "om"
            elif legacy_direction == "auto":
                detected = detect_direction_auto(text)
                source_lang, target_lang = ("om", "en") if detected == "om_en" else ("en", "om")

        if not _is_supported_lang(source_lang):
            source_lang = "om"
        if not _is_supported_lang(target_lang):
            target_lang = "en"
        if source_lang == target_lang:
            target_lang = "en" if source_lang != "en" else "om"

        if source_lang == "om" and target_lang == "en":
            direction = "om_en"
        elif source_lang == "en" and target_lang == "om":
            direction = "en_om"
        else:
            direction = f"{source_lang}_{target_lang}"

        if source_lang in ("om", "en"):
            matched, audio = find_exact_base_match(text, source_lang)

        # âœ… IMPORTANT: use multipart translator (handles commas + sentences correctly)
        tr = safe_translate_multilingual(text, source_lang, target_lang)
        result = tr["text"]
        is_exact = tr["is_exact"]
        is_phrase = tr["is_phrase"]
        is_auto_translation = tr["is_auto_translation"]
        tts_audio_url = tr["tts_audio_url"]

        if text and not result:
            if source_lang == "om" and target_lang not in ("om", "en"):
                base_en, _, _ = translate_multipart_text(text, "om_en")
                result = base_en
                translate_error = "Auto translation unavailable. Showing base Oromo-English result."
            elif source_lang == "en" and target_lang not in ("om", "en"):
                result = normalize_text(text)
                translate_error = "Auto translation unavailable. Showing base Oromo-English result."
            else:
                translate_error = "Translation service is temporarily unavailable. Please try again."

        record_search(text, direction, is_phrase, is_exact)

        if source_lang in ("om", "en") and target_lang in ("om", "en") and not is_exact:
            clean_exact = normalize_text(text)
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
        source_lang=source_lang,
        target_lang=target_lang,
        language_options=LANGUAGE_OPTIONS,
        result_is_rtl=_is_rtl_lang(target_lang),
        source_speech_lang=_speech_lang_code(source_lang),
        target_speech_lang=_speech_lang_code(target_lang),
        is_auto_translation=is_auto_translation,
        tts_audio_url=tts_audio_url,
        translate_error=translate_error,
        suggestions=suggestions,
        phrase_suggestions=phrase_suggestions,
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

            # âœ… IMPORTANT: avoid doubled punctuation when phrase already ends with . or ?
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

    # âœ… Grammar template check FIRST
    if direction == "en_om":
        for pattern, replacement in EN_OM_TEMPLATES:
            if pattern.match(seg):
                return replacement, 1, 1

    
    words = seg.split()
    out = []
    i = 0
    any_exact = 0
    any_phrase = 0

    while i < len(words):
        best_tr = None
        best_len = 0

        # Try phrases first (length >= 2)
        Lmax = min(max_phrase_words, len(words) - i)
        for L in range(Lmax, 1, -1):
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

        # ---- word fallback ----
        w = words[i]
        w_cf = w.casefold()

        # Drop safe English filler words in English->Oromo fallback
        if direction == "en_om" and (w_cf in EN_DROP_WORDS or w_cf in EN_SOFT_WORDS):
            i += 1
            continue

        wk = key_for(w)
        trw = lookup_word(cur, direction, wk) if wk else None
        if trw:
            out.append(trw)
            any_exact = 1
        else:
            out.append(w)

        i += 1

    result = " ".join(out)
    result = postprocess_segment(result, direction)
    return result, int(any_exact), int(any_phrase)



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
            repaired = 0

            conn = sqlite3.connect(DB_NAME)
            for en, om in pairs:
                _wid, was_inserted, was_repaired = _upsert_pending_word_base(conn, en, om)
                if was_inserted:
                    inserted += 1
                elif was_repaired:
                    repaired += 1
                else:
                    skipped += 1

            conn.commit()
            conn.close()

            msg = (
                f"Thanks! File submitted. "
                f"Added: {inserted} | Completed partial entries: {repaired} | Skipped duplicates: {skipped}. "
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
        _wid, was_inserted, was_repaired = _upsert_pending_word_base(conn, english_raw, oromo_raw)
        conn.commit()
        conn.close()

        if not was_inserted and not was_repaired:
            msg = "This word already exists (or is pending). Try another."
            return render_template("submit.html", msg=msg)
        if was_repaired:
            msg = "Existing partial entry was completed and is waiting for admin approval."
            return render_template("submit.html", msg=msg)

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
        repaired = 0

        conn = sqlite3.connect(DB_NAME)
        for en, om in pairs:
            _wid, was_inserted, was_repaired = _upsert_pending_word_base(conn, en, om)
            if was_inserted:
                inserted += 1
            elif was_repaired:
                repaired += 1
            else:
                skipped += 1

        conn.commit()
        conn.close()

        msg = (
            f"Thanks! File submitted. "
            f"Added: {inserted} | Completed partial entries: {repaired} | Skipped duplicates: {skipped}. "
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

    # âœ… Recorder uploads: replace existing audio (approved + pending) for this entry/lang
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
    # âœ… auto-approve for recorder
    c.execute("""
        INSERT INTO audio (entry_type, entry_id, lang, file_path, status)
        VALUES (?, ?, ?, ?, 'approved')
    """, (entry_type, entry_id, lang, rel_path))
    conn.commit()
    conn.close()

    url = _public_audio_url(rel_path)
    return jsonify({"ok": True, "message": "Saved âœ… Published now.", "url": url})


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

    # âœ… connect with timeout (prevents â€œstuck foreverâ€ on DB lock)
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
            # âœ… IMPORTANT: do deletes BEFORE saving file + inserting
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
            "message": ("Saved âœ… Published now." if is_recorder else "Oromo audio submitted for admin approval."),
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
    âœ… Oromo ONLY
    âœ… Allow unlimited pending submissions
    âœ… Block only if an APPROVED Oromo audio already exists for this entry
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


@app.route("/admin/debug/db-counts", methods=["GET"])
def admin_debug_db_counts():
    if not require_admin():
        return redirect("/admin")

    try:
        counts = _words_table_counts()
        payload = {
            "db_path": DB_NAME,
            **counts,
        }
        app.logger.info(f"admin_debug_db_counts db_path={DB_NAME} counts={counts}")
        return jsonify(payload)
    except Exception as e:
        app.logger.exception(f"admin_debug_db_counts failed: {repr(e)}")
        return jsonify({
            "error": "Could not read DB counts.",
            "db_path": DB_NAME
        }), 500


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

        if action in ("add_admin", "delete_admin"):
            msg = "Admin account changes are disabled here. Use password management only."

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
                        en_key = make_search_key(_strip_edge_punct(en))
                        om_key = make_search_key(_strip_edge_punct(om))
                        c.execute(
                            "UPDATE words SET english=?, oromo=?, english_key=?, oromo_key=? WHERE id=?",
                            (en, om, en_key, om_key, wid)
                        )
                        conn.commit()
                        clear_generated_translations_for_word(wid)
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
                clear_generated_translations_for_word(wid)
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
                        en_key = make_search_key(_strip_edge_punct(en))
                        om_key = make_search_key(_strip_edge_punct(om))
                        c.execute(
                            "UPDATE phrases SET english=?, oromo=?, english_key=?, oromo_key=? WHERE id=?",
                            (en, om, en_key, om_key, pid)
                        )
                        conn.commit()
                        upsert_phrase_aliases(pid, en, om, source="admin_manage")
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

def _find_word_by_english(conn, english_word: str):
    c = conn.cursor()
    norm = normalize_text(english_word or "")
    key = make_search_key(_strip_edge_punct(norm))
    if key:
        c.execute(
            "SELECT id, english, oromo FROM words WHERE english_key=? OR english=? LIMIT 1",
            (key, norm),
        )
    else:
        c.execute("SELECT id, english, oromo FROM words WHERE english=? LIMIT 1", (norm,))
    return c.fetchone()


def _count_missing_generated_langs(conn, word_id: int) -> int:
    if not word_id:
        return len(EXTRA_GENERATED_LANGS)
    try:
        c = conn.cursor()
        placeholders = ",".join("?" for _ in EXTRA_GENERATED_LANGS)
        c.execute(
            f"""
            SELECT COUNT(*)
            FROM generated_translations
            WHERE word_id=?
              AND lang_code IN ({placeholders})
              AND translated_text IS NOT NULL
              AND TRIM(translated_text) != ''
            """,
            (word_id, *EXTRA_GENERATED_LANGS),
        )
        row = c.fetchone()
        have_count = int((row or [0])[0] or 0)
        missing = len(EXTRA_GENERATED_LANGS) - have_count
        return missing if missing > 0 else 0
    except Exception:
        return len(EXTRA_GENERATED_LANGS)


@app.route("/admin/import", methods=["GET", "POST"])
def admin_import():
    if not require_admin():
        return redirect("/admin")

    msg = None
    conn = None

    try:
        if request.method == "POST":
            raw_words = []

            if request.is_json:
                data = request.get_json(silent=True) or {}
                incoming = data.get("words", [])
                if not isinstance(incoming, list):
                    return jsonify({"error": "JSON must include 'words' as a list"}), 400
                raw_words = [str(x) for x in incoming]
            else:
                f = request.files.get("file") or request.files.get("txt_file")
                if not f or not f.filename:
                    msg = "Please upload a TXT / CSV / XLSX file (English-only list)."
                    return render_template("admin_import.html", msg=msg)

                filename = (f.filename or "").lower().strip()
                data = f.read()

                try:
                    if filename.endswith(".txt"):
                        raw_words = parse_txt_english_rows(data)
                    elif filename.endswith(".csv"):
                        raw_words = parse_csv_english_rows(data)
                    elif filename.endswith(".xlsx"):
                        raw_words = parse_xlsx_english_rows(data)
                    else:
                        msg = "Only .txt, .csv, .xlsx files are supported."
                        return render_template("admin_import.html", msg=msg)
                except Exception as e:
                    app.logger.exception(f"admin_import parse error: {repr(e)}")
                    msg = "Could not read the file. Please check its format."
                    return render_template("admin_import.html", msg=msg)

            empty_rows = 0
            duplicate_rows = 0
            over_limit_rows = 0
            seen_keys = set()
            unique_words = []

            for raw in raw_words:
                w = normalize_text(raw or "")
                k = make_search_key(_strip_edge_punct(w))
                if not w or not k:
                    empty_rows += 1
                    continue
                if k in seen_keys:
                    duplicate_rows += 1
                    continue
                seen_keys.add(k)
                unique_words.append(w)

            if not unique_words:
                summary = (
                    f"No valid English words to import. Empty rows: {empty_rows} | "
                    f"Duplicates: {duplicate_rows}."
                )
                if request.is_json:
                    return jsonify({
                        "processed": 0,
                        "valid_unique_rows": 0,
                        "attempted_new_rows": 0,
                        "imported": 0,
                        "skipped_existing": 0,
                        "skipped_duplicate_rows": duplicate_rows,
                        "failed": 0,
                        "ignored_due_limit": 0,
                        "empty_rows": empty_rows,
                        "duplicate_rows": duplicate_rows,
                        "over_limit_rows": over_limit_rows,
                        "updated_missing_translations": 0,
                        "cached_generated_translations": 0,
                        "google_calls_used": 0,
                        "google_calls_max": IMPORT_MAX_CALLS,
                        "batch_size": IMPORT_BATCH_SIZE,
                        "max_words": IMPORT_MAX_WORDS,
                        "message": summary,
                    }), 400
                msg = summary
                return render_template("admin_import.html", msg=msg)

            total_chars = sum(len(x) for x in unique_words)

            inserted = 0
            skipped_existing = 0
            failed = 0
            cached_generated = 0
            updated_missing_translations = 0
            google_calls = 0

            conn = sqlite3.connect(DB_NAME)

            new_words = []
            words_for_cache = []

            for en in unique_words:
                existing = _find_word_by_english(conn, en)
                if existing:
                    skipped_existing += 1
                    wid = int(existing[0])
                    existing_en = normalize_text(existing[1] or "") or en
                    words_for_cache.append((wid, existing_en))
                else:
                    new_words.append(en)

            words_for_base_insert = new_words[:IMPORT_MAX_WORDS]
            over_limit_rows = max(0, len(new_words) - len(words_for_base_insert))

            for i in range(0, len(words_for_base_insert), IMPORT_BATCH_SIZE):
                batch = words_for_base_insert[i:i + IMPORT_BATCH_SIZE]
                if not batch:
                    continue

                try:
                    google_calls += 1
                    oms = google_translate_batch_v2(batch, target="om", source="en")

                    if oms and len(oms) == len(batch):
                        translated_pairs = list(zip(batch, oms))
                    else:
                        translated_pairs = []
                        for en in batch:
                            google_calls += 1
                            translated_pairs.append((en, google_translate_text_v2(en, target="om", source="en")))
                except Exception as batch_err:
                    app.logger.exception(f"admin_import batch translate failed: {repr(batch_err)}")
                    translated_pairs = [(en, "") for en in batch]

                for en, om in translated_pairs:
                    try:
                        om_text = normalize_text(om or "")
                        if not om_text:
                            failed += 1
                            continue

                        wid, was_inserted, _was_repaired = _upsert_pending_word_base(
                            conn, en, om_text, status="approved"
                        )
                        if not wid:
                            failed += 1
                            continue

                        if was_inserted:
                            inserted += 1
                        else:
                            skipped_existing += 1

                        words_for_cache.append((wid, normalize_text(en)))
                    except Exception as row_err:
                        app.logger.exception(f"admin_import row upsert failed for en={repr(en)}: {repr(row_err)}")
                        failed += 1
                        continue

            # Keep per-word items unique for cache accounting.
            unique_cache_items = []
            seen_ids = set()
            for wid, en in words_for_cache:
                if not wid or not en or wid in seen_ids:
                    continue
                seen_ids.add(wid)
                unique_cache_items.append((wid, en))

            missing_before = {}
            for wid, _en in unique_cache_items:
                missing_before[wid] = _count_missing_generated_langs(conn, wid)

            # Commit base inserts before cache warmup.
            # Cache warmup writes through separate SQLite connections; holding this
            # transaction open can trigger "database is locked" and skip cache writes.
            conn.commit()
            conn.close()
            conn = None

            try:
                cached_generated = _cache_extra_translations_for_words(unique_cache_items)
            except Exception as e:
                app.logger.exception(f"admin_import extra cache warmup failed: {repr(e)}")
                cached_generated = 0

            conn = sqlite3.connect(DB_NAME)
            for wid in missing_before.keys():
                before = missing_before.get(wid, 0)
                after = _count_missing_generated_langs(conn, wid)
                if after < before:
                    updated_missing_translations += 1

            conn.close()
            conn = None

            msg2 = (
                f"Import done. Valid unique rows: {len(unique_words)} | Attempted new rows: {len(words_for_base_insert)} | "
                f"Imported: {inserted} | Skipped existing: {skipped_existing} | Failed: {failed} | "
                f"Ignored due to limit: {over_limit_rows} | Empty rows: {empty_rows} | Duplicate rows in file: {duplicate_rows} | "
                f"Updated missing translations: {updated_missing_translations} | "
                f"Cached generated translations: {cached_generated} | Google calls used: {google_calls}."
            )
            msg = msg2

            if request.is_json:
                return jsonify({
                    "processed": len(raw_words),
                    "valid_unique_rows": len(unique_words),
                    "attempted_new_rows": len(words_for_base_insert),
                    "total_chars": total_chars,
                    "imported": inserted,
                    "skipped": skipped_existing,
                    "skipped_existing": skipped_existing,
                    "skipped_duplicate_rows": duplicate_rows,
                    "failed": failed,
                    "ignored_due_limit": over_limit_rows,
                    "empty_rows": empty_rows,
                    "duplicate_rows": duplicate_rows,
                    "over_limit_rows": over_limit_rows,
                    "updated_missing_translations": updated_missing_translations,
                    "cached_generated_translations": cached_generated,
                    "google_calls_used": google_calls,
                    "google_calls_max": IMPORT_MAX_CALLS,
                    "batch_size": IMPORT_BATCH_SIZE,
                    "max_words": IMPORT_MAX_WORDS,
                    "message": msg
                })

    except Exception as e:
        app.logger.exception(f"admin_import failed: {repr(e)}")
        safe_msg = "Import failed safely due to an internal error. Please check file format and try again."
        if request.method == "POST" and request.is_json:
            return jsonify({"error": safe_msg}), 500
        msg = safe_msg
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass

    try:
        return render_template("admin_import.html", msg=msg)
    except Exception as e:
        app.logger.exception(f"admin_import render failed: {repr(e)}")
        # Final guardrail: GET/POST should fail safely without a hard 500.
        return (
            "<h3>Admin import is temporarily unavailable.</h3>"
            "<p>Please return to dashboard and try again.</p>"
        ), 200


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
    Build a small â€œteacher styleâ€ response.
    """
    en = entry["english"]
    om = entry["oromo"]

    # very lightweight â€œlessonâ€
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
        "title": f"ðŸ“˜ {entry['type'].capitalize()} lesson",
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
                    "Hi! Iâ€™m **Gadaa AI (free demo)**.\n\n"
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

@app.after_request
def no_cache_html(resp):
    if resp.mimetype == "text/html":
        resp.headers["Cache-Control"] = "no-store, max-age=0"
        resp.headers["Pragma"] = "no-cache"
    return resp

# ------------------ RUN / MIGRATE ------------------

if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1 and sys.argv[1] == "migrate":
        ensure_key_columns()
        backfill_keys()
        ensure_key_indexes()
        print("DB migration done")
        sys.exit(0)   # âœ… VERY IMPORTANT â†’ stop here

    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)





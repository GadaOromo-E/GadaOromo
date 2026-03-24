#!/usr/bin/env python3
import argparse
import hashlib
import os
import re
import sqlite3
from collections import Counter, defaultdict


FILENAME_RE = re.compile(
    r"^tts_(word|phrase)_(\d+)_([A-Za-z0-9-]+)_([0-9a-f]{12})_(.+)\.mp3$"
)
VOICE_PROVIDER = "azure_speech"
EXTRA_LANGS = ("am", "ar", "fr", "zh-CN")


def normalize_text(text: str) -> str:
    t = (text or "").strip()
    t = t.replace("Ã¢â‚¬â„¢", "'").replace("Ã¢â‚¬Ëœ", "'").replace("`", "'")
    t = re.sub(r"\s+", " ", t).strip()
    return t


def text_hash(text: str) -> str:
    return hashlib.sha256(normalize_text(text).encode("utf-8")).hexdigest()


def load_schema(conn: sqlite3.Connection):
    cur = conn.cursor()
    cur.execute(
        """
        SELECT sql
        FROM sqlite_master
        WHERE type='table' AND name='generated_tts_audio'
        LIMIT 1
        """
    )
    table_sql = (cur.fetchone() or [""])[0] or ""
    cur.execute("PRAGMA table_info(generated_tts_audio)")
    cols = cur.fetchall()
    return table_sql, cols


def load_approved_base_texts(conn: sqlite3.Connection):
    cur = conn.cursor()
    words = {}
    phrases = {}

    cur.execute("SELECT id, english, oromo FROM words WHERE status='approved'")
    for wid, en, om in cur.fetchall():
        words[int(wid)] = {
            "en": normalize_text(en or ""),
            "om": normalize_text(om or ""),
        }

    cur.execute("SELECT id, english, oromo FROM phrases WHERE status='approved'")
    for pid, en, om in cur.fetchall():
        phrases[int(pid)] = {
            "en": normalize_text(en or ""),
            "om": normalize_text(om or ""),
        }

    return words, phrases


def load_generated_texts(conn: sqlite3.Connection):
    cur = conn.cursor()
    word_tr = defaultdict(dict)
    phrase_tr = defaultdict(dict)

    cur.execute(
        """
        SELECT word_id, lang_code, translated_text
        FROM generated_translations
        WHERE lang_code IN ('am', 'ar', 'fr', 'zh-CN')
          AND translated_text IS NOT NULL
          AND TRIM(translated_text) != ''
        """
    )
    for wid, lang, txt in cur.fetchall():
        norm = normalize_text(txt or "")
        if norm:
            word_tr[int(wid)][lang] = norm

    cur.execute(
        """
        SELECT phrase_id, lang_code, translated_text
        FROM generated_phrase_translations
        WHERE lang_code IN ('am', 'ar', 'fr', 'zh-CN')
          AND translated_text IS NOT NULL
          AND TRIM(translated_text) != ''
        """
    )
    for pid, lang, txt in cur.fetchall():
        norm = normalize_text(txt or "")
        if norm:
            phrase_tr[int(pid)][lang] = norm

    return word_tr, phrase_tr


def load_existing_unique_keys(conn: sqlite3.Connection):
    cur = conn.cursor()
    cur.execute(
        """
        SELECT entry_type, entry_id, lang_code, text_hash, voice_provider, voice_name
        FROM generated_tts_audio
        """
    )
    return {
        (
            row[0],
            int(row[1]),
            row[2],
            row[3],
            row[4],
            row[5],
        )
        for row in cur.fetchall()
    }


def resolve_text(
    entry_type: str,
    entry_id: int,
    lang_code: str,
    words: dict,
    phrases: dict,
    word_tr: dict,
    phrase_tr: dict,
) -> str:
    base_map = words if entry_type == "word" else phrases
    tr_map = word_tr if entry_type == "word" else phrase_tr

    base = base_map.get(entry_id)
    if not base:
        return ""
    if lang_code in ("en", "om"):
        return normalize_text(base.get(lang_code, "") or "")
    if lang_code in EXTRA_LANGS:
        return normalize_text((tr_map.get(entry_id, {}) or {}).get(lang_code, "") or "")
    return ""


def main():
    parser = argparse.ArgumentParser(
        description="Restore generated_tts_audio rows from existing static/uploads/tts_*.mp3 files."
    )
    parser.add_argument("--db", default="gadaoromo.db", help="Path to sqlite DB file.")
    parser.add_argument("--uploads-dir", default=os.path.join("static", "uploads"), help="Directory with tts_*.mp3 files.")
    parser.add_argument("--limit", type=int, default=0, help="Optional max number of files to scan.")
    parser.add_argument("--apply", action="store_true", help="Write inserts. Default is dry-run.")
    args = parser.parse_args()

    conn = sqlite3.connect(args.db)
    conn.row_factory = sqlite3.Row

    table_sql, cols = load_schema(conn)
    words, phrases = load_approved_base_texts(conn)
    word_tr, phrase_tr = load_generated_texts(conn)
    existing = load_existing_unique_keys(conn)

    print("== generated_tts_audio schema ==")
    print(table_sql)
    print("Columns:")
    for c in cols:
        print(f"- name={c[1]} type={c[2]} notnull={c[3]} pk={c[5]}")
    print("")

    if not os.path.isdir(args.uploads_dir):
        raise SystemExit(f"uploads-dir not found: {args.uploads_dir}")

    names = sorted(
        [
            n
            for n in os.listdir(args.uploads_dir)
            if n.startswith("tts_") and n.endswith(".mp3")
        ]
    )
    if args.limit and args.limit > 0:
        names = names[: args.limit]

    summary = Counter()
    by_lang = Counter()
    inserts = []

    for name in names:
        summary["files_scanned"] += 1
        m = FILENAME_RE.match(name)
        if not m:
            summary["skipped_bad_filename"] += 1
            continue

        entry_type, entry_id_raw, lang_code, hash12, voice_name = m.groups()
        entry_id = int(entry_id_raw)
        text_value = resolve_text(
            entry_type=entry_type,
            entry_id=entry_id,
            lang_code=lang_code,
            words=words,
            phrases=phrases,
            word_tr=word_tr,
            phrase_tr=phrase_tr,
        )
        if not text_value:
            summary["skipped_missing_text"] += 1
            continue

        th = text_hash(text_value)
        if not th.startswith(hash12):
            summary["skipped_hash_mismatch"] += 1
            continue

        file_path = f"uploads/{name}"
        key = (entry_type, entry_id, lang_code, th, VOICE_PROVIDER, voice_name)
        if key in existing:
            summary["already_present"] += 1
            continue

        inserts.append(
            (
                entry_type,
                entry_id,
                lang_code,
                text_value,
                th,
                VOICE_PROVIDER,
                voice_name,
                file_path,
            )
        )
        existing.add(key)
        summary["to_insert"] += 1
        by_lang[lang_code] += 1

    if args.apply and inserts:
        before_changes = conn.total_changes
        cur = conn.cursor()
        cur.executemany(
            """
            INSERT INTO generated_tts_audio
            (entry_type, entry_id, lang_code, text_value, text_hash, voice_provider, voice_name, file_path, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(entry_type, entry_id, lang_code, text_hash, voice_provider, voice_name) DO NOTHING
            """,
            inserts,
        )
        conn.commit()
        summary["inserted"] = int(conn.total_changes - before_changes)
    else:
        summary["inserted"] = 0

    print("== restore summary ==")
    print(f"mode={'APPLY' if args.apply else 'DRY_RUN'}")
    for k in (
        "files_scanned",
        "to_insert",
        "inserted",
        "already_present",
        "skipped_missing_text",
        "skipped_hash_mismatch",
        "skipped_bad_filename",
    ):
        print(f"{k}={summary.get(k, 0)}")
    print("by_lang_to_insert=" + str(dict(by_lang)))
    print("")

    print("== validation queries ==")
    print("SELECT COUNT(*) AS total_rows FROM generated_tts_audio;")
    print(
        "SELECT entry_type, lang_code, COUNT(*) AS n "
        "FROM generated_tts_audio GROUP BY entry_type, lang_code ORDER BY entry_type, lang_code;"
    )
    print(
        "SELECT COUNT(*) AS empty_text_rows "
        "FROM generated_tts_audio "
        "WHERE text_value IS NULL OR TRIM(text_value)='';"
    )
    print(
        "SELECT COUNT(*) AS non_uploads_rows "
        "FROM generated_tts_audio "
        "WHERE file_path NOT LIKE 'uploads/tts_%';"
    )
    print(
        "SELECT COUNT(*) AS duplicate_unique_rows "
        "FROM ("
        "  SELECT entry_type, entry_id, lang_code, text_hash, voice_provider, voice_name, COUNT(*) c "
        "  FROM generated_tts_audio "
        "  GROUP BY entry_type, entry_id, lang_code, text_hash, voice_provider, voice_name "
        "  HAVING c > 1"
        ");"
    )
    print("")

    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM generated_tts_audio")
    total = int((cur.fetchone() or [0])[0] or 0)
    print(f"post_total_rows={total}")
    cur.execute(
        """
        SELECT entry_type, lang_code, COUNT(*) AS n
        FROM generated_tts_audio
        GROUP BY entry_type, lang_code
        ORDER BY entry_type, lang_code
        """
    )
    rows = cur.fetchall()
    print("post_counts_by_entry_lang:")
    for r in rows:
        print(f"- {r[0]}:{r[1]}={r[2]}")
    cur.execute("SELECT COUNT(*) FROM generated_tts_audio WHERE text_value IS NULL OR TRIM(text_value)=''")
    print(f"post_empty_text_rows={int((cur.fetchone() or [0])[0] or 0)}")
    cur.execute("SELECT COUNT(*) FROM generated_tts_audio WHERE file_path NOT LIKE 'uploads/tts_%'")
    print(f"post_non_uploads_rows={int((cur.fetchone() or [0])[0] or 0)}")
    cur.execute(
        """
        SELECT COUNT(*) FROM (
            SELECT entry_type, entry_id, lang_code, text_hash, voice_provider, voice_name, COUNT(*) c
            FROM generated_tts_audio
            GROUP BY entry_type, entry_id, lang_code, text_hash, voice_provider, voice_name
            HAVING c > 1
        )
        """
    )
    print(f"post_duplicate_unique_rows={int((cur.fetchone() or [0])[0] or 0)}")

    conn.close()


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Diagnose Learn phrase loading limits (DB -> backend -> HTML)."""
import json
import os
import re
import sys
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


def analyze_production(url: str = "https://gadaadictionary.com/learn"):
    req = urllib.request.Request(url, headers={"User-Agent": "gadaa-learn-diagnose/1.0"})
    with urllib.request.urlopen(req, timeout=90) as resp:
        html = resp.read().decode("utf-8", "replace")
        headers = dict(resp.headers)
    comment = re.search(r"<!--\s*learn_debug\s+([^>]+)-->", html)
    fields = {}
    if comment:
        for part in comment.group(1).split():
            if "=" in part:
                k, v = part.split("=", 1)
                fields[k] = v
    phrase_json = len(re.findall(r'"entry_type"\s*:\s*"phrase"', html))
    rows_match = re.search(r"window\.LEARN_ROWS\s*=\s*(\[)", html)
    learn_rows_len = None
    if rows_match:
        start = rows_match.start(1)
        depth = 0
        for i, ch in enumerate(html[start:], start):
            if ch == "[":
                depth += 1
            elif ch == "]":
                depth -= 1
                if depth == 0:
                    try:
                        learn_rows_len = len(json.loads(html[start : i + 1]))
                    except json.JSONDecodeError:
                        learn_rows_len = None
                    break
    return {
        "url": url,
        "response_bytes": len(html.encode("utf-8")),
        "x_learn_headers": {k: v for k, v in headers.items() if "learn" in k.lower() or "gadaa" in k.lower()},
        "learn_debug_comment": fields,
        "phrase_json_markers": phrase_json,
        "learn_rows_json_len": learn_rows_len,
    }


def analyze_local_db():
    os.chdir(ROOT)
    import app as app_module

    limit = int(app_module.LEARN_RECENT_PHRASE_LIMIT)
    db = app_module.DB_NAME
    if not os.path.isfile(db):
        return {"db_path": db, "error": "db_missing"}

    import sqlite3

    conn = sqlite3.connect(db)
    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM phrases WHERE status='approved'")
    approved_total = int((c.fetchone() or [0])[0])
    c.execute(
        """
        SELECT COUNT(*)
        FROM (
            SELECT phrase_id
            FROM (
                SELECT gta.entry_id AS phrase_id,
                       LOWER(REPLACE(TRIM(gta.lang_code), '_', '-')) AS lang_key
                FROM generated_tts_audio gta
                WHERE gta.entry_type='phrase'
                  AND gta.file_path LIKE 'https://%'
                  AND gta.lang_code IS NOT NULL AND TRIM(gta.lang_code) != ''
                UNION
                SELECT gpt.phrase_id AS phrase_id,
                       LOWER(REPLACE(TRIM(gpt.lang_code), '_', '-')) AS lang_key
                FROM generated_phrase_translations gpt
                WHERE gpt.tts_audio_url LIKE 'https://%'
                  AND gpt.lang_code IS NOT NULL AND TRIM(gpt.lang_code) != ''
            ) audio_langs
            GROUP BY phrase_id
            HAVING COUNT(DISTINCT lang_key) >= 2
        ) eligible
        """
    )
    eligible_total = int((c.fetchone() or [0])[0])
    conn.close()

    rows = app_module._load_learn_rows()
    if isinstance(rows, tuple):
        rows, loader_stats = rows
    else:
        loader_stats = {}
    return {
        "db_path": db,
        "env_LEARN_RECENT_PHRASE_LIMIT": os.environ.get("LEARN_RECENT_PHRASE_LIMIT"),
        "resolved_LEARN_RECENT_PHRASE_LIMIT": limit,
        "approved_phrases_total": loader_stats.get("approved_phrases_total", approved_total),
        "eligible_multi_lang_https_total": loader_stats.get("eligible_multi_lang_https_total", eligible_total),
        "backend_rows_returned": len(rows),
        "loader_stats": loader_stats,
    }


def main():
    print("=== Local DB / backend ===")
    try:
        print(json.dumps(analyze_local_db(), indent=2))
    except Exception as e:
        print(json.dumps({"local_error": repr(e)}, indent=2))

    print("\n=== Production HTML ===")
    try:
        print(json.dumps(analyze_production(), indent=2))
    except Exception as e:
        print(json.dumps({"prod_error": repr(e)}, indent=2))


if __name__ == "__main__":
    main()

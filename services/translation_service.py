import os
import requests


def google_translate_batch(
    texts,
    target: str,
    source: str = "en",
    api_key: str = "",
    timeout: int = 30,
):
    """
    Google Translate v2 batch helper.
    Returns translated texts in the same order, or [] on failure.
    """
    key = (api_key or "").strip()
    if not key or not texts:
        return []

    url = "https://translation.googleapis.com/language/translate/v2"
    payload = {
        "q": list(texts),
        "source": source,
        "target": target,
        "format": "text",
    }

    try:
        # Avoid accidental broken proxy env drift unless explicitly requested.
        session = requests.Session()
        session.trust_env = (os.environ.get("OUTBOUND_TRUST_ENV", "0").strip() == "1")
        resp = session.post(url, params={"key": key}, json=payload, timeout=timeout)
        if resp.status_code != 200:
            return []
        data = resp.json() or {}
        translations = ((data.get("data") or {}).get("translations") or [])
        out = []
        for item in translations:
            out.append((item or {}).get("translatedText", "") or "")
        return out if len(out) == len(texts) else []
    except Exception:
        return []


def google_translate_text(
    text: str,
    target: str,
    source: str = "en",
    api_key: str = "",
    timeout: int = 30,
):
    text = (text or "").strip()
    if not text:
        return ""
    batch = google_translate_batch(
        [text],
        target=target,
        source=source,
        api_key=api_key,
        timeout=timeout,
    )
    return (batch[0] if batch else "").strip()


def _translation_table_info(entry_type: str):
    et = (entry_type or "").strip().lower()
    if et == "word":
        return "generated_translations", "word_id"
    if et == "phrase":
        return "generated_phrase_translations", "phrase_id"
    return "", ""


def get_or_generate_translation(db, entry_type, entry_id, source_text, target_lang, api_key):
    """
    DB-first translation cache helper.
    Supports the app schema:
    - words -> generated_translations(word_id, ...)
    - phrases -> generated_phrase_translations(phrase_id, ...)
    """
    table, id_col = _translation_table_info(entry_type)
    if not table or not id_col:
        return ""
    text = (source_text or "").strip()
    if not text:
        return ""

    cur = db.cursor()
    cur.execute(
        f"""
        SELECT translated_text
        FROM {table}
        WHERE {id_col}=? AND lang_code=?
          AND translated_text IS NOT NULL
          AND TRIM(translated_text) != ''
        LIMIT 1
        """,
        (int(entry_id or 0), target_lang),
    )
    row = cur.fetchone()
    if row and row[0]:
        return (row[0] or "").strip()

    translated = google_translate_text(
        text,
        target=target_lang,
        source="en",
        api_key=api_key,
    )
    if not translated:
        return ""

    cur.execute(
        f"""
        INSERT INTO {table}
        ({id_col}, lang_code, translated_text, provider, updated_at)
        VALUES (?, ?, ?, 'google_translate_v2', CURRENT_TIMESTAMP)
        ON CONFLICT({id_col}, lang_code) DO UPDATE SET
            translated_text=excluded.translated_text,
            provider='google_translate_v2',
            updated_at=CURRENT_TIMESTAMP
        """,
        (int(entry_id or 0), target_lang, translated),
    )
    db.commit()
    return translated

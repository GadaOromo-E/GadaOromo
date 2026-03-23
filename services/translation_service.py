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
        resp = requests.post(url, params={"key": key}, json=payload, timeout=timeout)
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

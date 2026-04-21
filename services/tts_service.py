import hashlib
import os
import logging
import random
import time


logger = logging.getLogger(__name__)


def _int_env(name: str, default: int) -> int:
    try:
        return int((os.environ.get(name, str(default)) or str(default)).strip() or default)
    except Exception:
        return int(default)


def _azure_429_retry_settings() -> dict:
    max_retries = max(0, min(_int_env("AZURE_TTS_429_MAX_RETRIES", 2), 6))
    base_backoff_ms = max(50, min(_int_env("AZURE_TTS_429_BASE_BACKOFF_MS", 500), 10000))
    max_backoff_ms = max(base_backoff_ms, min(_int_env("AZURE_TTS_429_MAX_BACKOFF_MS", 4000), 60000))
    jitter_ms = max(0, min(_int_env("AZURE_TTS_429_JITTER_MS", 250), 5000))
    return {
        "max_retries": int(max_retries),
        "base_backoff_ms": int(base_backoff_ms),
        "max_backoff_ms": int(max_backoff_ms),
        "jitter_ms": int(jitter_ms),
    }


def _is_azure_429_error(error_text: str) -> bool:
    e = (error_text or "").strip().lower()
    if not e:
        return False
    return ("429" in e) or ("too many requests" in e)


def _is_remote_ref(file_path: str) -> bool:
    fp = (file_path or "").strip().lower()
    return fp.startswith("http://") or fp.startswith("https://")


def _local_basename_from_ref(file_path: str) -> str:
    fp = (file_path or "").replace("\\", "/").strip()
    if not fp or _is_remote_ref(fp):
        return ""
    return os.path.basename(fp)


def _file_is_nonempty(path: str) -> bool:
    try:
        return bool(path and os.path.isfile(path) and (os.path.getsize(path) > 0))
    except Exception:
        return False


def azure_synthesize_mp3(
    text: str,
    speech_key: str,
    speech_region: str,
    voice_name: str = "",
    speech_lang: str = "",
):
    """
    Azure Speech synthesis helper.
    Returns: (audio_bytes, error_message)
    """
    clean_text = (text or "").strip()
    if not clean_text:
        return b"", "empty_text"

    key = (speech_key or "").strip()
    region = (speech_region or "").strip()
    if not key or not region:
        return b"", "missing_azure_credentials"

    try:
        import azure.cognitiveservices.speech as speechsdk
    except Exception:
        return b"", "azure_speech_sdk_not_installed"

    retry_cfg = _azure_429_retry_settings()
    max_retries = int(retry_cfg.get("max_retries", 0) or 0)
    base_backoff_ms = int(retry_cfg.get("base_backoff_ms", 500) or 500)
    max_backoff_ms = int(retry_cfg.get("max_backoff_ms", 4000) or 4000)
    jitter_ms = int(retry_cfg.get("jitter_ms", 250) or 250)

    attempt = 0
    while True:
        try:
            config = speechsdk.SpeechConfig(subscription=key, region=region)
            config.set_speech_synthesis_output_format(
                speechsdk.SpeechSynthesisOutputFormat.Audio24Khz48KBitRateMonoMp3
            )
            if voice_name:
                config.speech_synthesis_voice_name = voice_name
            if speech_lang:
                config.speech_synthesis_language = speech_lang

            # None output target -> returns audio bytes in memory.
            synthesizer = speechsdk.SpeechSynthesizer(speech_config=config, audio_config=None)
            result = synthesizer.speak_text_async(clean_text).get()

            if result.reason == speechsdk.ResultReason.SynthesizingAudioCompleted:
                return bytes(result.audio_data or b""), ""

            if result.reason == speechsdk.ResultReason.Canceled:
                details = speechsdk.SpeechSynthesisCancellationDetails(result)
                msg = str(details.error_details or details.reason or "tts_canceled")
                if _is_azure_429_error(msg) and attempt < max_retries:
                    delay_ms = min(max_backoff_ms, int(base_backoff_ms * (2 ** attempt)))
                    if jitter_ms > 0:
                        delay_ms += int(random.uniform(0, jitter_ms))
                    attempt += 1
                    logger.warning(
                        "azure_tts_retry_429 attempt=%s/%s delay_ms=%s voice=%s speech_lang=%s",
                        attempt,
                        max_retries,
                        int(delay_ms),
                        (voice_name or ""),
                        (speech_lang or ""),
                    )
                    time.sleep(max(0.0, float(delay_ms) / 1000.0))
                    continue
                return b"", f"azure_tts_canceled:{msg}"

            return b"", f"azure_tts_failed:{result.reason}"
        except Exception as exc:
            err_text = f"azure_tts_exception:{repr(exc)}"
            if _is_azure_429_error(err_text) and attempt < max_retries:
                delay_ms = min(max_backoff_ms, int(base_backoff_ms * (2 ** attempt)))
                if jitter_ms > 0:
                    delay_ms += int(random.uniform(0, jitter_ms))
                attempt += 1
                logger.warning(
                    "azure_tts_retry_429_exception attempt=%s/%s delay_ms=%s voice=%s speech_lang=%s",
                    attempt,
                    max_retries,
                    int(delay_ms),
                    (voice_name or ""),
                    (speech_lang or ""),
                )
                time.sleep(max(0.0, float(delay_ms) / 1000.0))
                continue
            return b"", err_text


def generate_and_store_tts(
    db,
    entry_type,
    entry_id,
    lang_code,
    text,
    speech_key,
    speech_region,
    voice_name="",
    speech_lang="",
    upload_dir="",
    output_filename="",
    voice_provider="azure_speech",
):
    clean_text = (text or "").strip()
    if not clean_text:
        return ""

    target_dir = (
        (upload_dir or "").strip()
        or (os.environ.get("AUDIO_UPLOAD_DIR", "").strip())
        or (os.environ.get("UPLOAD_FOLDER", "").strip())
        or "/data/uploads"
    )

    text_hash = hashlib.sha256(clean_text.encode("utf-8")).hexdigest()
    cur = db.cursor()
    cur.execute(
        """
        SELECT file_path
        FROM generated_tts_audio
        WHERE entry_type=? AND entry_id=? AND lang_code=? AND text_hash=?
          AND voice_provider=? AND voice_name=?
        ORDER BY id DESC
        LIMIT 1
        """,
        (entry_type, int(entry_id or 0), lang_code, text_hash, (voice_provider or "azure_speech"), (voice_name or "").strip()),
    )
    row = cur.fetchone()
    if row and row[0]:
        existing_ref = (row[0] or "").strip()
        if _is_remote_ref(existing_ref):
            return existing_ref
        existing_name = _local_basename_from_ref(existing_ref)
        existing_abs = os.path.join(target_dir, existing_name) if existing_name else ""
        if _file_is_nonempty(existing_abs):
            return existing_ref
        # Stale DB metadata: file row exists but file is missing; continue and regenerate.

    audio_bytes, err = azure_synthesize_mp3(
        clean_text,
        speech_key=speech_key,
        speech_region=speech_region,
        voice_name=voice_name,
        speech_lang=speech_lang,
    )
    if err or not audio_bytes:
        return ""

    safe_name = (output_filename or "").strip() or f"tts_{entry_type}_{entry_id}_{lang_code}_{text_hash[:12]}.mp3"
    os.makedirs(target_dir, exist_ok=True)
    abs_path = os.path.join(target_dir, safe_name)
    with open(abs_path, "wb") as fh:
        fh.write(audio_bytes)
    exists_after_write = _file_is_nonempty(abs_path)
    file_size = os.path.getsize(abs_path) if os.path.isfile(abs_path) else 0
    file_ref = f"uploads/{safe_name}"
    playback_url = f"/uploads/{safe_name}"

    if not exists_after_write:
        return ""

    cur.execute(
        """
        INSERT INTO generated_tts_audio
        (entry_type, entry_id, lang_code, text_value, text_hash, voice_provider, voice_name, file_path, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
        ON CONFLICT(entry_type, entry_id, lang_code, text_hash, voice_provider, voice_name) DO UPDATE SET
            file_path=excluded.file_path
        """,
        (
            entry_type,
            int(entry_id or 0),
            lang_code,
            clean_text,
            text_hash,
            (voice_provider or "azure_speech"),
            (voice_name or "").strip(),
            file_ref,
        ),
    )
    db.commit()
    if str(entry_type or "").strip().lower() == "phrase":
        logger.info(
            "phrase_tts_service_write entry_id=%s lang=%s abs_save_path=%s exists_after_write=%s file_size=%s db_file_path=%s playback_url=%s",
            int(entry_id or 0),
            lang_code,
            abs_path,
            exists_after_write,
            int(file_size or 0),
            file_ref,
            playback_url,
        )
    return file_ref

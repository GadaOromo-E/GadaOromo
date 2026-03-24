import hashlib
import os
import tempfile

from services.blob_service import upload_file


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
            msg = (details.error_details or details.reason or "tts_canceled")
            return b"", f"azure_tts_canceled:{msg}"

        return b"", f"azure_tts_failed:{result.reason}"
    except Exception as exc:
        return b"", f"azure_tts_exception:{repr(exc)}"


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
):
    clean_text = (text or "").strip()
    if not clean_text:
        return ""

    text_hash = hashlib.md5(clean_text.encode("utf-8")).hexdigest()
    cur = db.cursor()
    cur.execute(
        """
        SELECT file_path
        FROM generated_tts_audio
        WHERE entry_type=? AND entry_id=? AND lang_code=? AND text_hash=?
        ORDER BY id DESC
        LIMIT 1
        """,
        (entry_type, int(entry_id or 0), lang_code, text_hash),
    )
    row = cur.fetchone()
    if row and row[0]:
        return (row[0] or "").strip()

    audio_bytes, err = azure_synthesize_mp3(
        clean_text,
        speech_key=speech_key,
        speech_region=speech_region,
        voice_name=voice_name,
        speech_lang=speech_lang,
    )
    if err or not audio_bytes:
        return ""

    filename = f"tts_{entry_type}_{entry_id}_{lang_code}_{text_hash}.mp3"
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".mp3")
    try:
        tmp.write(audio_bytes)
        tmp.close()
        blob_url = upload_file(tmp.name, filename)
        if not blob_url:
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
                "azure",
                (voice_name or "").strip(),
                blob_url,
            ),
        )
        db.commit()
        return blob_url
    finally:
        try:
            os.unlink(tmp.name)
        except Exception:
            pass

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

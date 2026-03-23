-- Phrase-level generated translations cache (English pivot -> target language)
CREATE TABLE IF NOT EXISTS generated_phrase_translations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    phrase_id INTEGER NOT NULL,
    lang_code TEXT NOT NULL,
    translated_text TEXT NOT NULL,
    provider TEXT NOT NULL DEFAULT 'google_translate_v2',
    tts_audio_url TEXT,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(phrase_id, lang_code)
);

CREATE INDEX IF NOT EXISTS idx_generated_phrase_translations_phrase_id
ON generated_phrase_translations(phrase_id);

CREATE INDEX IF NOT EXISTS idx_generated_phrase_translations_lang_code
ON generated_phrase_translations(lang_code);

-- Generated TTS cache metadata (audio files are stored on disk under uploads/)
CREATE TABLE IF NOT EXISTS generated_tts_audio (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    entry_type TEXT NOT NULL,           -- word | phrase
    entry_id INTEGER NOT NULL,
    lang_code TEXT NOT NULL,            -- en, am, ar, fr, zh-CN
    text_value TEXT NOT NULL,
    text_hash TEXT NOT NULL,
    voice_provider TEXT NOT NULL DEFAULT 'azure_speech',
    voice_name TEXT NOT NULL,
    file_path TEXT NOT NULL,            -- uploads/<file>.mp3
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(entry_type, entry_id, lang_code, text_hash, voice_provider, voice_name)
);

CREATE INDEX IF NOT EXISTS idx_generated_tts_audio_entry
ON generated_tts_audio(entry_type, entry_id);

CREATE INDEX IF NOT EXISTS idx_generated_tts_audio_lang
ON generated_tts_audio(lang_code);

CREATE INDEX IF NOT EXISTS idx_generated_tts_audio_hash
ON generated_tts_audio(text_hash);

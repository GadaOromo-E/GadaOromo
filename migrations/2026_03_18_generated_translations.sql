-- Phase 1 multilingual expansion cache table
CREATE TABLE IF NOT EXISTS generated_translations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    word_id INTEGER NOT NULL,
    lang_code TEXT NOT NULL,
    translated_text TEXT NOT NULL,
    provider TEXT NOT NULL DEFAULT 'google_translate_v2',
    tts_audio_url TEXT,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(word_id, lang_code)
);

CREATE INDEX IF NOT EXISTS idx_generated_translations_word_id
ON generated_translations(word_id);

CREATE INDEX IF NOT EXISTS idx_generated_translations_lang_code
ON generated_translations(lang_code);

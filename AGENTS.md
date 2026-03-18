\# AGENTS.md



\## Project: Gadaa Dictionary



This is a Flask-based multilingual dictionary project with Oromo-English as the editable base dictionary.



\## Core product rules



1\. \*\*Oromo-English is the source of truth\*\*

&#x20;  - Base dictionary entries are Oromo + English.

&#x20;  - Admin can edit/delete base entries.

&#x20;  - Do not replace the base DB logic with machine translation logic.



2\. \*\*English is the pivot language\*\*

&#x20;  - Extra languages are generated from English.

&#x20;  - Supported extra languages:

&#x20;    - Amharic (`am`)

&#x20;    - Arabic (`ar`)

&#x20;    - French (`fr`)

&#x20;    - Chinese Simplified (`zh-CN`)



3\. \*\*Do not reintroduce approval workflows\*\*

&#x20;  - Generated translations do not need admin approval.

&#x20;  - Admin management should remain focused on base dictionary entry maintenance.



4\. \*\*Oromo audio workflow must remain untouched\*\*

&#x20;  - Oromo audio recording/submission flow already exists.

&#x20;  - Do not remove or redesign Oromo audio recording behavior.



5\. \*\*Do not add paid/cloud features unless explicitly requested\*\*

&#x20;  - Do not add billing-dependent features unless the task explicitly requests it.

&#x20;  - If external APIs are used, ensure safe fallback behavior when unavailable.



\## Architecture rules



\### Backend

\- Main backend is in `app.py`.

\- Preserve existing base Oromo-English lookup behavior.

\- Any multilingual feature must sit on top of the base lookup, not replace it.

\- Fail safely:

&#x20; - no 500 errors for missing generated translations

&#x20; - no crashes if external provider fails

&#x20; - render fallback UI/messages instead



\### Database

\- Existing DB contains base Oromo-English entries.

\- Generated translations are cached separately.

\- Do not make destructive schema changes.

\- Prefer additive migrations only.



\### Templates

Important templates:

\- `templates/index.html`

\- `templates/dictionary.html`

\- `templates/translate.html`

\- `templates/words.html`

\- `templates/admin\_manage.html`



Guidelines:

\- Keep server-rendered HTML as the primary output.

\- Do not rely only on JavaScript for important content.

\- Arabic text must use RTL where appropriate.



\## SEO rules



1\. Word pages are important SEO landing pages.

2\. Preserve clean canonical URLs.

3\. Prefer stable canonical URLs over `request.url` if query params may appear.

4\. Word pages should include:

&#x20;  - strong `<title>`

&#x20;  - strong meta description

&#x20;  - visible multilingual HTML content

&#x20;  - JSON-LD structured data where useful

5\. Do not break sitemap behavior if present.



\## UI/UX rules



1\. Dictionary page should prioritize \*\*finding base entries first\*\*.

2\. Translate page can use stricter source/target logic.

3\. Dictionary should feel like lookup first, translation second.

4\. Preserve existing styling as much as possible.

5\. Avoid unnecessary redesigns.

6\. On mobile, keep behavior simple and stable.



\## Coding style



\- Make the \*\*smallest safe change\*\*.

\- Prefer clear helper functions over large rewrites.

\- Add inline comments when behavior changes significantly.

\- Preserve backwards compatibility whenever possible.

\- If uncertain, add a TODO comment instead of risky changes.



\## Safety checks before finalizing changes



Before reporting completion:

1\. Ensure base Oromo-English dictionary still works.

2\. Ensure `/dictionary` still renders correctly.

3\. Ensure `/translate` still renders correctly.

4\. Ensure word detail pages still render.

5\. Ensure no crashes on missing cache/provider failures.

6\. Ensure DB runtime artifacts are not intentionally included.



\## Files that should not be committed accidentally



\- `\_\_pycache\_\_/`

\- `\*.pyc`

\- `gadaoromo.db-journal`

\- runtime temp files

\- broken/unintended untracked files



If `.gitignore` is missing, recommend adding one.



\## Preferred task workflow



For non-trivial tasks:

1\. Read repository first

2\. Produce plan

3\. Implement in small safe changes

4\. Report exact files changed

5\. Report any TODOs or risks


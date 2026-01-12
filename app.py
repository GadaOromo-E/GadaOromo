# -*- coding: utf-8 -*-
"""
Created on Sun Jan 11 16:32:35 2026

@author: ademo
"""

import os
print("RUNNING APP FROM:", os.path.abspath(__file__))
print("TEMPLATES FOLDER:", os.path.join(os.path.dirname(os.path.abspath(__file__)), "templates"))

import sqlite3
from flask import Flask, render_template, request, redirect, session
from werkzeug.security import generate_password_hash, check_password_hash
from jinja2 import TemplateNotFound

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "gadaoromo_secret_key_change_me")

DB_NAME = "gadaoromo.db"


# ------------------ DATABASE ------------------

def get_conn():
    return sqlite3.connect(DB_NAME)

def init_db():
    conn = get_conn()
    c = conn.cursor()

    # Words table
    c.execute("""
        CREATE TABLE IF NOT EXISTS words (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            english TEXT,
            oromo TEXT,
            status TEXT DEFAULT 'pending'
        )
    """)

    # Admin table
    c.execute("""
        CREATE TABLE IF NOT EXISTS admin (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT UNIQUE,
            password TEXT
        )
    """)

    conn.commit()
    conn.close()

def ensure_first_admin():
    """
    Creates the first admin if none exists.
    Uses environment variables if provided, otherwise defaults.
    """
    default_email = os.environ.get("ADMIN_EMAIL", "jewargure1@gmail.com")
    default_password = os.environ.get("ADMIN_PASSWORD", "admin123")  # change later!

    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM admin")
    count = c.fetchone()[0]

    if count == 0:
        c.execute(
            "INSERT INTO admin (email, password) VALUES (?, ?)",
            (default_email, generate_password_hash(default_password))
        )
        conn.commit()

    conn.close()


init_db()
ensure_first_admin()


# ------------------ TRANSLATOR (V1) ------------------

def translate_text(text: str, direction: str = "om_en") -> str:
    """
    Very simple starter translator:
    - Direct phrase match
    - Word-by-word fallback
    Expand later with real dataset + AI.
    """
    # IMPORTANT: direction is here for future use (can store separate maps)
    # For now, we keep one map with both directions included.
    dictionary = {
        # English -> Oromo
        "hello": "akkam",
        "hi": "akkam",
        "how are you": "akkam jirta",
        "thank you": "galatoomi",
        "good morning": "ganama gaarii",
        "good night": "halkan gaarii",
        "bye": "nagaatti",
        "water": "bishaan",

        # Oromo -> English
        "akkam": "hello",
        "akkam jirta": "how are you",
        "galatoomi": "thank you",
        "ganama gaarii": "good morning",
        "halkan gaarii": "good night",
        "nagaatti": "bye",
        "bishaan": "water",
    }

    t = (text or "").lower().strip()
    if not t:
        return ""

    # Direct phrase match
    if t in dictionary:
        return dictionary[t]

    # Word-by-word fallback
    words = t.split()
    out = [dictionary.get(w, w) for w in words]
    return " ".join(out)


# ------------------ HELPERS ------------------

def render_safe(template_name: str, **context):
    """
    If a template file is missing, show a simple fallback HTML instead of crashing.
    """
    try:
        return render_template(template_name, **context)
    except TemplateNotFound:
        # Minimal fallback (so site keeps working)
        return f"""
        <h2>Template missing: {template_name}</h2>
        <p>Please create it inside the <b>templates</b> folder.</p>
        <p>Context keys available: {", ".join(context.keys())}</p>
        <p><a href="/">Go Home</a></p>
        """


# ------------------ HOME (Dictionary + Quick Translator) ------------------

@app.route("/", methods=["GET", "POST"])
def home():
    result = None
    translation = ""
    direction = "om_en"

    if request.method == "POST":
        # 1) Translator form (Quick Translator on homepage)
        if "translate_text" in request.form:
            direction = request.form.get("direction", "om_en")
            text = request.form.get("translate_text", "")
            translation = translate_text(text, direction)

        # 2) Dictionary search form (supports both "word" and "query")
        else:
            search_word = (
                request.form.get("word")
                or request.form.get("query")
                or ""
            ).lower().strip()

            if search_word:
                conn = get_conn()
                c = conn.cursor()
                c.execute("""
                    SELECT english, oromo
                    FROM words
                    WHERE status='approved'
                      AND (english=? OR oromo=?)
                    """, (search_word, search_word))
                result = c.fetchone()
                conn.close()

    # Fetch approved words (optional for listing page)
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT english, oromo FROM words WHERE status='approved' ORDER BY english ASC")
    all_words = c.fetchall()
    conn.close()

    return render_safe(
        "index.html",
        result=result,
        words=all_words,
        translation=translation,
        direction=direction
    )


# ------------------ PUBLIC SUBMISSION ------------------

@app.route("/submit", methods=["GET", "POST"])
def submit():
    if request.method == "POST":
        english = request.form.get("english", "").lower().strip()
        oromo = request.form.get("oromo", "").lower().strip()

        if not english or not oromo:
            return "Please provide both English and Oromo. <a href='/submit'>Try again</a>"

        conn = get_conn()
        c = conn.cursor()
        c.execute(
            "INSERT INTO words (english, oromo, status) VALUES (?, ?, 'pending')",
            (english, oromo)
        )
        conn.commit()
        conn.close()

        return "Thank you! Your submission is waiting for admin approval. <br><a href='/'>Go back</a>"

    return render_safe("submit.html")


# ------------------ TRANSLATE PAGE ------------------

@app.route("/translate", methods=["GET", "POST"])
def translate():
    result = ""
    direction = "om_en"
    text = ""

    if request.method == "POST":
        direction = request.form.get("direction", "om_en")
        text = request.form.get("text", "")
        result = translate_text(text, direction)

    return render_safe("translate.html", result=result, direction=direction, text=text)


# ------------------ ADMIN LOGIN ------------------

@app.route("/admin", methods=["GET", "POST"])
def admin_login():
    if request.method == "POST":
        email = request.form.get("email", "").strip()
        password = request.form.get("password", "")

        conn = get_conn()
        c = conn.cursor()
        c.execute("SELECT id, password FROM admin WHERE email=?", (email,))
        admin = c.fetchone()
        conn.close()

        if admin and check_password_hash(admin[1], password):
            session["admin"] = admin[0]
            return redirect("/dashboard")
        return "Invalid login. <a href='/admin'>Try again</a>"

    return render_safe("admin_login.html")


# ------------------ ADMIN DASHBOARD ------------------

@app.route("/dashboard")
def dashboard():
    if "admin" not in session:
        return redirect("/admin")

    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT id, english, oromo FROM words WHERE status='pending' ORDER BY id DESC")
    pending = c.fetchall()
    conn.close()

    return render_safe("admin_dashboard.html", pending=pending)


@app.route("/approve/<int:word_id>")
def approve(word_id):
    if "admin" not in session:
        return redirect("/admin")

    conn = get_conn()
    c = conn.cursor()
    c.execute("UPDATE words SET status='approved' WHERE id=?", (word_id,))
    conn.commit()
    conn.close()

    return redirect("/dashboard")


@app.route("/reject/<int:word_id>")
def reject(word_id):
    if "admin" not in session:
        return redirect("/admin")

    conn = get_conn()
    c = conn.cursor()
    c.execute("DELETE FROM words WHERE id=? AND status='pending'", (word_id,))
    conn.commit()
    conn.close()

    return redirect("/dashboard")


@app.route("/logout")
def logout():
    session.pop("admin", None)
    return redirect("/")


# ------------------ RUN (Render-compatible) ------------------

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)

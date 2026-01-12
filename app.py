# -*- coding: utf-8 -*-
"""
Created on Sun Jan 11 16:32:35 2026

@author: ademo
"""

from flask import Flask, render_template, request, redirect, session
import sqlite3
from werkzeug.security import generate_password_hash, check_password_hash
import os

app = Flask(__name__)
app.secret_key = "gadaoromo_secret_key"

DB_NAME = "gadaoromo.db"

# ------------------ DATABASE SETUP ------------------

def init_db():
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()

    # Words table
    c.execute("""
        CREATE TABLE IF NOT EXISTS words (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            english TEXT,
            oromo TEXT,
            status TEXT
        )
    """)

    # Phrases table
    c.execute("""
        CREATE TABLE IF NOT EXISTS phrases (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            english TEXT,
            oromo TEXT,
            status TEXT
        )
    """)

    # Admin table
    c.execute("""
        CREATE TABLE IF NOT EXISTS admin (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT,
            password TEXT
        )
    """)

    conn.commit()
    conn.close()

init_db()

# ------------------ TRANSLATION LOGIC (PHRASES FIRST, THEN WORDS) ------------------

def translate_text(text: str, direction: str = "om_en") -> str:
    t = (text or "").lower().strip()
    if not t:
        return ""

    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()

    # 1) Phrase exact match
    if direction == "om_en":
        c.execute("SELECT english FROM phrases WHERE status='approved' AND oromo=?", (t,))
        row = c.fetchone()
        if row:
            conn.close()
            return row[0]
    else:
        c.execute("SELECT oromo FROM phrases WHERE status='approved' AND english=?", (t,))
        row = c.fetchone()
        if row:
            conn.close()
            return row[0]

    # 2) Word exact match
    if direction == "om_en":
        c.execute("SELECT english FROM words WHERE status='approved' AND oromo=?", (t,))
        row = c.fetchone()
        if row:
            conn.close()
            return row[0]
    else:
        c.execute("SELECT oromo FROM words WHERE status='approved' AND english=?", (t,))
        row = c.fetchone()
        if row:
            conn.close()
            return row[0]

    # 3) Word-by-word fallback
    tokens = t.split()
    out = []
    for w in tokens:
        if direction == "om_en":
            c.execute("SELECT english FROM words WHERE status='approved' AND oromo=?", (w,))
            r = c.fetchone()
            out.append(r[0] if r else w)
        else:
            c.execute("SELECT oromo FROM words WHERE status='approved' AND english=?", (w,))
            r = c.fetchone()
            out.append(r[0] if r else w)

    conn.close()
    return " ".join(out)

# ------------------ HOME PAGE ------------------

@app.route("/", methods=["GET", "POST"])
def home():
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()

    result = None
    if request.method == "POST":
        word = request.form.get("word", "").lower().strip()
        c.execute(
            "SELECT english, oromo FROM words WHERE status='approved' AND (english=? OR oromo=?)",
            (word, word)
        )
        result = c.fetchone()

    c.execute("SELECT english, oromo FROM words WHERE status='approved' ORDER BY english ASC")
    all_words = c.fetchall()
    conn.close()

    return render_template("index.html", result=result, words=all_words)

# ------------------ TRANSLATOR PAGE (AUTO DETECT) ------------------

@app.route("/translate", methods=["GET", "POST"])
def translate():
    result = None
    text = ""
    direction = "auto"

    if request.method == "POST":
        text = request.form.get("text", "")
        direction = request.form.get("direction", "auto")
        t = (text or "").lower().strip()

        if direction == "auto":
            tokens = t.split()

            conn = sqlite3.connect(DB_NAME)
            c = conn.cursor()

            oromo_hits = 0
            english_hits = 0

            # Token matches in words
            for w in tokens:
                c.execute("SELECT 1 FROM words WHERE status='approved' AND oromo=?", (w,))
                if c.fetchone():
                    oromo_hits += 1

                c.execute("SELECT 1 FROM words WHERE status='approved' AND english=?", (w,))
                if c.fetchone():
                    english_hits += 1

            # Whole sentence matches in phrases (weighted)
            c.execute("SELECT 1 FROM phrases WHERE status='approved' AND oromo=?", (t,))
            if c.fetchone():
                oromo_hits += 3

            c.execute("SELECT 1 FROM phrases WHERE status='approved' AND english=?", (t,))
            if c.fetchone():
                english_hits += 3

            conn.close()

            if oromo_hits > english_hits:
                direction = "om_en"
            elif english_hits > oromo_hits:
                direction = "en_om"
            else:
                direction = "en_om"

        result = translate_text(text, direction)

    return render_template("translate.html", result=result, text=text, direction=direction)

# ------------------ PUBLIC SUBMISSION (WORDS) ------------------

@app.route("/submit", methods=["GET", "POST"])
def submit():
    if request.method == "POST":
        english = request.form.get("english", "").lower().strip()
        oromo = request.form.get("oromo", "").lower().strip()

        if not english or not oromo:
            return "Please provide both English and Oromo. <a href='/submit'>Try again</a>"

        conn = sqlite3.connect(DB_NAME)
        c = conn.cursor()
        c.execute("INSERT INTO words (english, oromo, status) VALUES (?, ?, 'pending')", (english, oromo))
        conn.commit()
        conn.close()

        return "Thank you! Your word is waiting for admin approval. <br><a href='/'>Go back</a>"

    return render_template("submit.html")

# ------------------ PUBLIC SUBMISSION (PHRASES) ------------------

@app.route("/submit_phrase", methods=["GET", "POST"])
def submit_phrase():
    if request.method == "POST":
        english = request.form.get("english", "").lower().strip()
        oromo = request.form.get("oromo", "").lower().strip()

        if not english or not oromo:
            return "Please provide both English and Oromo phrase. <a href='/submit_phrase'>Try again</a>"

        conn = sqlite3.connect(DB_NAME)
        c = conn.cursor()
        c.execute("INSERT INTO phrases (english, oromo, status) VALUES (?, ?, 'pending')", (english, oromo))
        conn.commit()
        conn.close()

        return "Thank you! Your phrase is waiting for admin approval. <br><a href='/'>Go back</a>"

    return render_template("submit_phrase.html")

# ------------------ ADMIN LOGIN ------------------

@app.route("/admin", methods=["GET", "POST"])
def admin_login():
    if request.method == "POST":
        email = request.form.get("email", "").strip()
        password = request.form.get("password", "")

        conn = sqlite3.connect(DB_NAME)
        c = conn.cursor()
        c.execute("SELECT id, password FROM admin WHERE email=?", (email,))
        admin = c.fetchone()
        conn.close()

        if admin and check_password_hash(admin[1], password):
            session["admin"] = admin[0]
            return redirect("/dashboard")

        return "Invalid login"

    return render_template("admin_login.html")

# ------------------ ADMIN DASHBOARD ------------------

@app.route("/dashboard")
def dashboard():
    if "admin" not in session:
        return redirect("/admin")

    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()

    c.execute("SELECT id, english, oromo FROM words WHERE status='pending' ORDER BY id DESC")
    pending_words = c.fetchall()

    c.execute("SELECT id, english, oromo FROM phrases WHERE status='pending' ORDER BY id DESC")
    pending_phrases = c.fetchall()

    conn.close()

    return render_template("admin_dashboard.html",
                           pending=pending_words,
                           pending_phrases=pending_phrases)

# ------------------ APPROVE / REJECT WORDS ------------------

@app.route("/approve/<int:word_id>")
def approve(word_id):
    if "admin" not in session:
        return redirect("/admin")

    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("UPDATE words SET status='approved' WHERE id=?", (word_id,))
    conn.commit()
    conn.close()

    return redirect("/dashboard")

@app.route("/reject/<int:word_id>")
def reject(word_id):
    if "admin" not in session:
        return redirect("/admin")

    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("DELETE FROM words WHERE id=? AND status='pending'", (word_id,))
    conn.commit()
    conn.close()

    return redirect("/dashboard")

# ------------------ APPROVE / REJECT PHRASES ------------------

@app.route("/approve_phrase/<int:phrase_id>")
def approve_phrase(phrase_id):
    if "admin" not in session:
        return redirect("/admin")

    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("UPDATE phrases SET status='approved' WHERE id=?", (phrase_id,))
    conn.commit()
    conn.close()

    return redirect("/dashboard")

@app.route("/reject_phrase/<int:phrase_id>")
def reject_phrase(phrase_id):
    if "admin" not in session:
        return redirect("/admin")

    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("DELETE FROM phrases WHERE id=? AND status='pending'", (phrase_id,))
    conn.commit()
    conn.close()

    return redirect("/dashboard")

# ------------------ LOGOUT ------------------

@app.route("/logout")
def logout():
    session.pop("admin", None)
    return redirect("/")

# ------------------ CREATE FIRST ADMIN (RUN ONCE) ------------------

@app.route("/create_admin")
def create_admin():
    email = "jewargure1@gmail.com"
    password = generate_password_hash("admin123")

    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("INSERT INTO admin (email, password) VALUES (?, ?)", (email, password))
    conn.commit()
    conn.close()

    return "Admin created. You can now login."

# ------------------ RUN ------------------

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)

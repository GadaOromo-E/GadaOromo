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

# ------------------ DATABASE SETUP ------------------

def init_db():
    conn = sqlite3.connect("gadaoromo.db")
    c = conn.cursor()

    c.execute("""
        CREATE TABLE IF NOT EXISTS words (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            english TEXT,
            oromo TEXT,
            status TEXT
        )
    """)

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

# ------------------ TRANSLATION LOGIC (DB-POWERED) ------------------

def translate_text(text: str, direction: str = "om_en") -> str:
    t = (text or "").lower().strip()
    if not t:
        return ""

    conn = sqlite3.connect("gadaoromo.db")
    c = conn.cursor()

    # 1) Exact phrase match
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

    # 2) Word-by-word fallback
    words = t.split()
    out = []

    for w in words:
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
    conn = sqlite3.connect("gadaoromo.db")
    c = conn.cursor()

    result = None

    if request.method == "POST":
        word = request.form.get("word", "").lower()
        c.execute("SELECT english, oromo FROM words WHERE status='approved' AND (english=? OR oromo=?)", (word, word))
        result = c.fetchone()

    c.execute("SELECT english, oromo FROM words WHERE status='approved'")
    all_words = c.fetchall()

    conn.close()
    return render_template("index.html", result=result, words=all_words)

# ------------------ TRANSLATOR PAGE ------------------

@app.route("/translate", methods=["GET", "POST"])
def translate():
    result = None
    text = ""
    direction = "om_en"

    if request.method == "POST":
        text = request.form.get("text", "")
        direction = request.form.get("direction", "om_en")
        result = translate_text(text, direction)

    return render_template("translate.html", result=result, text=text, direction=direction)

# ------------------ PUBLIC SUBMISSION ------------------

@app.route("/submit", methods=["GET", "POST"])
def submit():
    if request.method == "POST":
        english = request.form["english"].lower()
        oromo = request.form["oromo"].lower()

        conn = sqlite3.connect("gadaoromo.db")
        c = conn.cursor()
        c.execute("INSERT INTO words (english, oromo, status) VALUES (?, ?, 'pending')", (english, oromo))
        conn.commit()
        conn.close()

        return "Thank you! Your submission is waiting for admin approval. <br><a href='/'>Go back</a>"

    return render_template("submit.html")

# ------------------ ADMIN LOGIN ------------------

@app.route("/admin", methods=["GET", "POST"])
def admin_login():
    if request.method == "POST":
        email = request.form["email"]
        password = request.form["password"]

        conn = sqlite3.connect("gadaoromo.db")
        c = conn.cursor()
        c.execute("SELECT id, password FROM admin WHERE email=?", (email,))
        admin = c.fetchone()
        conn.close()

        if admin and check_password_hash(admin[1], password):
            session["admin"] = admin[0]
            return redirect("/dashboard")
        else:
            return "Invalid login"

    return render_template("admin_login.html")

# ------------------ ADMIN DASHBOARD ------------------

@app.route("/dashboard")
def dashboard():
    if "admin" not in session:
        return redirect("/admin")

    conn = sqlite3.connect("gadaoromo.db")
    c = conn.cursor()
    c.execute("SELECT id, english, oromo FROM words WHERE status='pending'")
    pending = c.fetchall()
    conn.close()

    return render_template("admin_dashboard.html", pending=pending)

# ------------------ APPROVE WORD ------------------

@app.route("/approve/<int:word_id>")
def approve(word_id):
    if "admin" not in session:
        return redirect("/admin")

    conn = sqlite3.connect("gadaoromo.db")
    c = conn.cursor()
    c.execute("UPDATE words SET status='approved' WHERE id=?", (word_id,))
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

    conn = sqlite3.connect("gadaoromo.db")
    c = conn.cursor()
    c.execute("INSERT INTO admin (email, password) VALUES (?, ?)", (email, password))
    conn.commit()
    conn.close()

    return "Admin created. You can now login."

# ------------------ RUN ------------------

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)

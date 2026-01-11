# -*- coding: utf-8 -*-
"""
Created on Sun Jan 11 16:32:35 2026

@author: ademo
"""

from flask import Flask, render_template, request, redirect, session
import sqlite3
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)
app.secret_key = "gadaoromo_secret_key"

# ------------------ DATABASE SETUP ------------------

def init_db():
    conn = sqlite3.connect("gadaoromo.db")
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

# ------------------ HOME PAGE ------------------

@app.route("/", methods=["GET", "POST"])
def home():
    conn = sqlite3.connect("gadaoromo.db")
    c = conn.cursor()

    result = None

    if request.method == "POST":
        word = request.form["word"].lower()
        c.execute("SELECT english, oromo FROM words WHERE status='approved' AND (english=? OR oromo=?)", (word, word))
        result = c.fetchone()

    c.execute("SELECT english, oromo FROM words WHERE status='approved'")
    all_words = c.fetchall()

    conn.close()

    return render_template("index.html", result=result, words=all_words)

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

# ------------------

import os

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)


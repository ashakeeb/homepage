import sqlite3
import hashlib


def connect():
    return sqlite3.connect("users.db")


def create_table():
    db = connect()
    cursor = db.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            username TEXT PRIMARY KEY,
            password TEXT NOT NULL
        )
    """)

    db.commit()
    db.close()


def register_user(username, password):
    password = hashlib.sha256(password.encode()).hexdigest()

    db = connect()
    cursor = db.cursor()

    try:
        cursor.execute(
            "INSERT INTO users (username, password) VALUES (?, ?)",
            (username, password)
        )
        db.commit()
        result = True
    except sqlite3.IntegrityError:
        result = False

    db.close()
    return result


def check_login(username, password):
    password = hashlib.sha256(password.encode()).hexdigest()

    db = connect()
    cursor = db.cursor()

    cursor.execute(
        "SELECT * FROM users WHERE username = ? AND password = ?",
        (username, password)
    )

    user = cursor.fetchone()

    db.close()

    return user is not None
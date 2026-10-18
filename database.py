import sqlite3
import re
from werkzeug.security import generate_password_hash, check_password_hash

DATABASE = "fixbh.db"


def get_db_connection():
    db = sqlite3.connect(DATABASE)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys = ON")
    return db


def create_table():
    db = get_db_connection()

    db.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            email TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            role TEXT NOT NULL
                CHECK (role IN ('customer', 'provider', 'admin'))
        )
    """)

    # Add username if the database does not already have it.
    columns = db.execute("PRAGMA table_info(users)").fetchall()
    column_names = [column["name"] for column in columns]

    if "username" not in column_names:
        db.execute("ALTER TABLE users ADD COLUMN username TEXT")

    # Give existing accounts a username if they do not have one.
    db.execute("""
        UPDATE users
        SET username = 'user_' || id
        WHERE username IS NULL OR username = ''
    """)

    # Prevent duplicate usernames.
    db.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS idx_users_username
        ON users(username)
    """)

    db.commit()
    db.close()


def validate_password(password):
    if len(password) < 8:
        return "Password must be at least 8 characters long."

    if not re.search(r"[A-Z]", password):
        return "Password must contain at least one uppercase letter."

    if not re.search(r"[a-z]", password):
        return "Password must contain at least one lowercase letter."

    if not re.search(r"[0-9]", password):
        return "Password must contain at least one number."

    return None


def register_user(name, username, email, password, role):
    db = get_db_connection()

    try:
        if role not in ("customer", "provider"):
            return False

        password_hash = generate_password_hash(password)

        db.execute("""
            INSERT INTO users
                (name, username, email, password_hash, role)
            VALUES (?, ?, ?, ?, ?)
        """, (name, username, email, password_hash, role))

        db.commit()
        return True

    except sqlite3.IntegrityError:
        return False

    finally:
        db.close()

def check_login(identifier, password):
    db = get_db_connection()

    try:
        user = db.execute("""
            SELECT *
            FROM users
            WHERE username = ? OR email = ?
        """, (identifier, identifier)).fetchone()

        if user and check_password_hash(user["password_hash"], password):
            return user

        return None

    finally:
        db.close()
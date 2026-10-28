# db.py - SQLite database for customer accounts, wallet, visits and points
import sqlite3
import json
from datetime import datetime
from werkzeug.security import generate_password_hash, check_password_hash

DB_FILE = "smartstore.db"
POINTS_PER_DOLLAR = 1


def connect():
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    return conn


def add_column(conn, table, column, definition):
    """Add a column to an existing table (so your step 1 database keeps working)."""
    cols = [r["name"] for r in conn.execute(f"PRAGMA table_info({table})")]
    if column not in cols:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")


def init_db():
    with connect() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS customers (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                name            TEXT NOT NULL,
                email           TEXT NOT NULL UNIQUE,
                pin_hash        TEXT NOT NULL,
                face_consent    INTEGER NOT NULL DEFAULT 0,
                face_registered INTEGER NOT NULL DEFAULT 0,
                points          INTEGER NOT NULL DEFAULT 0,
                created_at      TEXT NOT NULL
            )""")
        conn.execute("""
            CREATE TABLE IF NOT EXISTS visits (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                customer_id   INTEGER NOT NULL,
                entry_time    TEXT NOT NULL,
                exit_time     TEXT,
                items         TEXT,
                total         REAL,
                points_earned INTEGER DEFAULT 0,
                ref_id        TEXT,
                FOREIGN KEY (customer_id) REFERENCES customers(id)
            )""")
        add_column(conn, "customers", "wallet", "REAL NOT NULL DEFAULT 0")
        add_column(conn, "visits", "paid", "INTEGER NOT NULL DEFAULT 1")
        add_column(conn, "visits", "exit_reason", "TEXT")


def now():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


# ─── Customers ───
def create_customer(name, email, pin, face_consent):
    try:
        with connect() as conn:
            cur = conn.execute(
                "INSERT INTO customers (name, email, pin_hash, face_consent, created_at) VALUES (?, ?, ?, ?, ?)",
                (name.strip(), email.strip().lower(), generate_password_hash(pin), int(bool(face_consent)), now()))
            return cur.lastrowid
    except sqlite3.IntegrityError:
        return None   # email already used


def check_login(email, pin):
    c = get_customer_by_email(email)
    if c and check_password_hash(c["pin_hash"], pin):
        return c
    return None


def get_customer(customer_id):
    with connect() as conn:
        row = conn.execute("SELECT * FROM customers WHERE id = ?", (customer_id,)).fetchone()
        return dict(row) if row else None


def get_customer_by_email(email):
    with connect() as conn:
        row = conn.execute("SELECT * FROM customers WHERE email = ?", (email.strip().lower(),)).fetchone()
        return dict(row) if row else None


def get_names():
    """{customer id: name} for everyone with a registered face (used by the Pi for its logs)."""
    with connect() as conn:
        rows = conn.execute("SELECT id, name FROM customers WHERE face_registered = 1").fetchall()
    return {r["id"]: r["name"] for r in rows}


def set_face_registered(customer_id, value=True):
    with connect() as conn:
        conn.execute("UPDATE customers SET face_registered = ? WHERE id = ?", (int(value), customer_id))


def public(c):
    """Customer info that is safe to send to the app (no PIN hash)."""
    out = {k: c[k] for k in ("id", "name", "email", "face_consent", "face_registered", "points")}
    out["wallet"] = round(c["wallet"], 2)
    return out


# ─── Wallet (simulated, no real money) ───
def top_up(customer_id, amount):
    with connect() as conn:
        conn.execute("UPDATE customers SET wallet = wallet + ? WHERE id = ?", (amount, customer_id))


def charge(customer_id, amount):
    """Take money from the wallet. Returns False if there isn't enough."""
    with connect() as conn:
        cur = conn.execute("UPDATE customers SET wallet = wallet - ? WHERE id = ? AND wallet >= ?",
                           (amount, customer_id, amount))
        return cur.rowcount == 1


# ─── Visits ───
def start_visit(customer_id):
    with connect() as conn:
        cur = conn.execute("INSERT INTO visits (customer_id, entry_time) VALUES (?, ?)", (customer_id, now()))
        return cur.lastrowid


def finish_visit(visit_id, items, total, ref_id, paid=True, reason="paynow"):
    """Close the visit. Points are only added once it's paid."""
    points = int(total * POINTS_PER_DOLLAR) if paid else 0
    with connect() as conn:
        row = conn.execute("SELECT customer_id FROM visits WHERE id = ?", (visit_id,)).fetchone()
        if not row:
            return 0
        conn.execute(
            """UPDATE visits SET exit_time = ?, items = ?, total = ?, points_earned = ?, ref_id = ?,
               paid = ?, exit_reason = ? WHERE id = ?""",
            (now(), json.dumps(items), total, points, ref_id, int(paid), reason, visit_id))
        conn.execute("UPDATE customers SET points = points + ? WHERE id = ?", (points, row["customer_id"]))
    return points


def get_unpaid(customer_id):
    with connect() as conn:
        rows = conn.execute(
            "SELECT * FROM visits WHERE customer_id = ? AND exit_time IS NOT NULL AND paid = 0 ORDER BY id",
            (customer_id,)).fetchall()
    return [dict(r) for r in rows]


def pay_unpaid(customer_id):
    """Try to pay old unpaid bills from the wallet. Returns the visits that got paid."""
    paid = []
    for v in get_unpaid(customer_id):
        if not charge(customer_id, v["total"]):
            break
        points = int(v["total"] * POINTS_PER_DOLLAR)
        with connect() as conn:
            conn.execute("UPDATE visits SET paid = 1, points_earned = ? WHERE id = ?", (points, v["id"]))
            conn.execute("UPDATE customers SET points = points + ? WHERE id = ?", (points, customer_id))
        v["points_earned"] = points
        v["items"] = json.loads(v["items"]) if v["items"] else []
        paid.append(v)
    return paid


def get_visits(customer_id, limit=10):
    with connect() as conn:
        rows = conn.execute(
            "SELECT * FROM visits WHERE customer_id = ? AND exit_time IS NOT NULL ORDER BY id DESC LIMIT ?",
            (customer_id, limit)).fetchall()
    visits = []
    for r in rows:
        v = dict(r)
        v["items"] = json.loads(v["items"]) if v["items"] else []
        visits.append(v)
    return visits

"""StockSentry - Smart Stock Alert
Multi-user inventory tracker: roles, low-stock flags, restock orders and audit trail.
"""
import csv
import io
import os
import re
import secrets
import sqlite3
import time
import urllib.parse
import urllib.request
from datetime import datetime
from functools import wraps

from flask import (Flask, Response, abort, flash, g, jsonify, redirect,
                   render_template, request, session, url_for)
from werkzeug.security import check_password_hash, generate_password_hash

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.environ.get("DB_PATH", os.path.join(BASE_DIR, "data", "stocksentry.db"))
ADMIN_USER = os.environ.get("ADMIN_USER", "admin")
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "admin123")
ALLOW_SIGNUP = os.environ.get("ALLOW_SIGNUP", "1") != "0"
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT = os.environ.get("TELEGRAM_CHAT_ID", "")

app = Flask(__name__)
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "dev-secret-change-me")
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
app.config["MAX_CONTENT_LENGTH"] = 2 * 1024 * 1024  # 2 MB upload cap

# ------------------------------------------------------------ roles & permissions
ROLES = ["admin", "manager", "staff", "viewer"]
ROLE_INFO = {
    "admin": "Full access: manages team, products and orders",
    "manager": "Adds/edits products, adjusts stock, creates restock orders",
    "staff": "Can view and use stock (decrease only)",
    "viewer": "Read-only access",
}
PERMS = {
    "use": {"admin", "manager", "staff"},      # decrease stock
    "edit": {"admin", "manager"},              # add / edit / increase / import
    "delete": {"admin"},
    "orders": {"admin", "manager"},
    "users": {"admin"},
}

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT NOT NULL UNIQUE COLLATE NOCASE,
    password_hash TEXT NOT NULL,
    role TEXT NOT NULL DEFAULT 'viewer',
    active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    last_login TEXT
);
CREATE TABLE IF NOT EXISTS products (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    sku TEXT UNIQUE,
    name TEXT NOT NULL,
    category TEXT NOT NULL DEFAULT 'General',
    supplier TEXT NOT NULL DEFAULT '',
    unit TEXT NOT NULL DEFAULT 'pcs',
    quantity INTEGER NOT NULL DEFAULT 0,
    min_level INTEGER NOT NULL DEFAULT 0,
    price REAL NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS movements (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    product_id INTEGER,
    product_name TEXT NOT NULL,
    change INTEGER NOT NULL,
    qty_after INTEGER NOT NULL,
    reason TEXT NOT NULL DEFAULT '',
    user TEXT NOT NULL DEFAULT 'system',
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS orders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    supplier TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'ordered',
    created_by TEXT NOT NULL,
    created_at TEXT NOT NULL,
    closed_by TEXT,
    closed_at TEXT
);
CREATE TABLE IF NOT EXISTS order_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    order_id INTEGER NOT NULL,
    product_id INTEGER,
    product_name TEXT NOT NULL,
    unit TEXT NOT NULL DEFAULT 'pcs',
    qty INTEGER NOT NULL,
    unit_price REAL NOT NULL DEFAULT 0
);
"""

DEMO = [
    # name, sku, category, supplier, unit, qty, min, price
    ("A4 Paper Ream", "STA-001", "Stationery", "PaperHub", "reams", 4, 10, 280),
    ("Blue Ballpoint Pens", "STA-002", "Stationery", "PaperHub", "boxes", 22, 8, 120),
    ("Whiteboard Markers", "STA-003", "Stationery", "PaperHub", "packs", 2, 6, 95),
    ("Spiral Notebooks", "STA-004", "Stationery", "PaperHub", "pcs", 60, 25, 45),
    ("Stapler Pins", "STA-005", "Stationery", "OfficeMart", "boxes", 0, 5, 30),
    ("Printer Ink - Black", "ELE-001", "Electronics", "TechSupply", "cartridges", 3, 3, 899),
    ("USB Flash Drive 32GB", "ELE-002", "Electronics", "TechSupply", "pcs", 14, 5, 350),
    ("HDMI Cable", "ELE-003", "Electronics", "TechSupply", "pcs", 1, 4, 220),
    ("AA Batteries", "ELE-004", "Electronics", "TechSupply", "packs", 18, 10, 150),
    ("Bottled Water 1L", "BEV-001", "Beverages", "FreshCo", "bottles", 48, 40, 20),
    ("Instant Coffee", "BEV-002", "Beverages", "FreshCo", "jars", 5, 6, 310),
    ("Tea Bags", "BEV-003", "Beverages", "FreshCo", "boxes", 9, 4, 180),
    ("Paper Cups", "BEV-004", "Beverages", "FreshCo", "sleeves", 7, 12, 55),
    ("Hand Sanitizer", "CLN-001", "Cleaning", "CleanPro", "bottles", 11, 6, 110),
    ("Garbage Bags", "CLN-002", "Cleaning", "CleanPro", "rolls", 3, 8, 90),
    ("Floor Cleaner", "CLN-003", "Cleaning", "CleanPro", "bottles", 15, 5, 160),
    ("First Aid Kit", "SAF-001", "Safety", "MediCare", "kits", 2, 2, 750),
    ("Event T-Shirts (M)", "MER-001", "Merchandise", "PrintWorks", "pcs", 35, 15, 260),
]
DEMO_TEAM = [("manager1", "manager"), ("staff1", "staff"), ("viewer1", "viewer")]
DEMO_PASSWORD = "Demo@1234"


# ---------------------------------------------------------------- database
def get_db():
    if "db" not in g:
        os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
        g.db = sqlite3.connect(DB_PATH, timeout=30)
        g.db.row_factory = sqlite3.Row
    return g.db


@app.teardown_appcontext
def close_db(_exc):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def now():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def init_db():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    # Several gunicorn workers run this at the same moment, so every step must be safe to repeat.
    with sqlite3.connect(DB_PATH, timeout=30) as db:
        db.executescript(SCHEMA)
        # migrate databases created by the single-user version
        cols = [r[1] for r in db.execute("PRAGMA table_info(movements)")]
        if "user" not in cols:
            try:
                db.execute("ALTER TABLE movements ADD COLUMN user TEXT NOT NULL DEFAULT 'system'")
            except sqlite3.OperationalError:
                pass  # another worker already added it
        if db.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 0:
            db.execute("INSERT OR IGNORE INTO users (username,password_hash,role,created_at) VALUES (?,?,?,?)",
                       (ADMIN_USER, generate_password_hash(ADMIN_PASSWORD), "admin", now()))


init_db()


# ---------------------------------------------------------------- helpers
def status_of(qty, min_level):
    if qty <= 0:
        return "out"
    if qty <= min_level:
        return "low"
    return "ok"


def enrich(row):
    d = dict(row)
    d["status"] = status_of(d["quantity"], d["min_level"])
    target = max(d["min_level"] * 2, d["min_level"] + 1)
    d["reorder"] = max(target - d["quantity"], 0) if d["status"] != "ok" else 0
    d["value"] = round(d["quantity"] * d["price"], 2)
    d["cost"] = round(d["reorder"] * d["price"], 2)
    d["pct"] = 100 if d["min_level"] == 0 else min(100, round(d["quantity"] / (d["min_level"] * 2) * 100))
    return d


def all_products():
    rows = get_db().execute("SELECT * FROM products ORDER BY name COLLATE NOCASE").fetchall()
    return [enrich(r) for r in rows]


def on_order_ids():
    rows = get_db().execute(
        "SELECT DISTINCT oi.product_id FROM order_items oi JOIN orders o ON o.id=oi.order_id "
        "WHERE o.status='ordered' AND oi.product_id IS NOT NULL").fetchall()
    return {r[0] for r in rows}


def actor():
    return g.user["username"] if g.get("user") else "system"


def log_move(db, pid, name, change, after, reason):
    db.execute(
        "INSERT INTO movements (product_id, product_name, change, qty_after, reason, user, created_at)"
        " VALUES (?,?,?,?,?,?,?)", (pid, name, change, after, reason, actor(), now()))


def telegram_configured():
    return bool(TELEGRAM_TOKEN and TELEGRAM_CHAT)


def send_telegram(text):
    if not telegram_configured():
        return False, "Telegram is not configured (set TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID)."
    try:
        data = urllib.parse.urlencode({"chat_id": TELEGRAM_CHAT, "text": text}).encode()
        req = urllib.request.Request(
            f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage", data=data)
        with urllib.request.urlopen(req, timeout=8) as resp:
            return resp.status == 200, "Alert sent to Telegram."
    except Exception as exc:  # network errors must never break the app
        return False, f"Could not send alert: {exc}"


def alert_text(items):
    lines = ["StockSentry alert - items need restocking:"]
    for p in items[:20]:
        tag = "OUT" if p["status"] == "out" else "LOW"
        lines.append(f"[{tag}] {p['name']}: {p['quantity']} left (min {p['min_level']}), order {p['reorder']} {p['unit']}")
    return "\n".join(lines)


def csv_safe(v):
    """Prevent CSV/Excel formula injection."""
    s = str(v)
    return "'" + s if s[:1] in ("=", "+", "-", "@") else s


def csv_response(filename, header, rows):
    buf = io.StringIO()
    buf.write("﻿")  # BOM so Excel opens UTF-8 correctly
    w = csv.writer(buf)
    w.writerow(header)
    for r in rows:
        w.writerow([csv_safe(c) for c in r])
    return Response(buf.getvalue(), mimetype="text/csv",
                    headers={"Content-Disposition": f"attachment; filename={filename}"})


def to_int(v, default=0, minimum=0):
    try:
        return max(int(float(v)), minimum)
    except (TypeError, ValueError):
        return default


def to_float(v, default=0.0):
    try:
        return max(float(v), 0.0)
    except (TypeError, ValueError):
        return default


USERNAME_RE = re.compile(r"^[A-Za-z0-9_.-]{3,30}$")


def check_new_credentials(username, password, confirm=None):
    if not USERNAME_RE.match(username):
        return "Username must be 3-30 characters: letters, numbers, dot, dash or underscore."
    if len(password) < 8:
        return "Password must be at least 8 characters."
    if confirm is not None and password != confirm:
        return "Passwords do not match."
    return None


# ---------------------------------------------------------------- security / auth
def can(perm):
    u = g.get("user")
    return bool(u) and u["role"] in PERMS.get(perm, set())


def needs(perm=None):
    """Require login, and optionally a permission."""
    def deco(fn):
        @wraps(fn)
        def wrapper(*a, **kw):
            if not g.get("user"):
                if request.is_json or request.path.startswith("/api/"):
                    return jsonify(error="login required"), 401
                return redirect(url_for("login", next=request.path))
            if perm and not can(perm):
                if request.is_json or request.path.startswith("/api/"):
                    return jsonify(error="You do not have permission to do that."), 403
                flash("You do not have permission to do that.", "error")
                return redirect(url_for("dashboard"))
            return fn(*a, **kw)
        return wrapper
    return deco


@app.before_request
def load_user_and_csrf():
    if "csrf" not in session:
        session["csrf"] = secrets.token_hex(16)
    g.user = None
    uid = session.get("uid")
    if uid:
        row = get_db().execute("SELECT * FROM users WHERE id=? AND active=1", (uid,)).fetchone()
        if row:
            g.user = dict(row)
        else:
            session.pop("uid", None)  # deleted or deactivated while signed in
    if request.method == "POST":
        token = request.form.get("csrf") or request.headers.get("X-CSRF-Token")
        if not token or not secrets.compare_digest(token, session["csrf"]):
            abort(400, "Invalid CSRF token")


@app.context_processor
def inject_globals():
    return {"csrf": session.get("csrf", ""), "user": g.get("user"), "can": can,
            "roles": ROLES, "role_info": ROLE_INFO, "telegram_on": telegram_configured(),
            "signup_on": ALLOW_SIGNUP, "demo_hint": ADMIN_PASSWORD == "admin123"}


@app.after_request
def security_headers(resp):
    resp.headers["X-Content-Type-Options"] = "nosniff"
    resp.headers["X-Frame-Options"] = "DENY"
    resp.headers["Referrer-Policy"] = "same-origin"
    return resp


_attempts = {}  # ip -> [timestamps]; simple brute-force protection


def too_many_attempts(ip):
    recent = [t for t in _attempts.get(ip, []) if time.time() - t < 300]
    _attempts[ip] = recent
    return len(recent) >= 6


def start_session(user_row):
    session.clear()
    session["uid"] = user_row["id"]
    session["csrf"] = secrets.token_hex(16)
    db = get_db()
    db.execute("UPDATE users SET last_login=? WHERE id=?", (now(), user_row["id"]))
    db.commit()


def safe_next():
    dest = request.args.get("next", "")
    return dest if dest.startswith("/") and not dest.startswith("//") else url_for("dashboard")


@app.route("/login", methods=["GET", "POST"])
def login():
    if g.user:
        return redirect(url_for("dashboard"))
    if request.method == "POST":
        ip = request.remote_addr or "?"
        if too_many_attempts(ip):
            flash("Too many failed attempts. Please wait a few minutes.", "error")
            return render_template("login.html")
        u = request.form.get("username", "").strip()
        p = request.form.get("password", "")
        row = get_db().execute("SELECT * FROM users WHERE username=?", (u,)).fetchone()
        good = check_password_hash(row["password_hash"] if row else generate_password_hash("x"), p)
        if row and good and row["active"]:
            _attempts.pop(ip, None)
            start_session(row)
            return redirect(safe_next())
        _attempts.setdefault(ip, []).append(time.time())
        flash("This account is disabled." if row and good and not row["active"]
              else "Wrong username or password.", "error")
    return render_template("login.html")


@app.route("/register", methods=["GET", "POST"])
def register():
    if not ALLOW_SIGNUP:
        abort(404)
    if g.user:
        return redirect(url_for("dashboard"))
    if request.method == "POST":
        u = request.form.get("username", "").strip()
        err = check_new_credentials(u, request.form.get("password", ""), request.form.get("confirm", ""))
        if err:
            flash(err, "error")
        else:
            db = get_db()
            try:
                cur = db.execute("INSERT INTO users (username,password_hash,role,created_at) VALUES (?,?,?,?)",
                                 (u, generate_password_hash(request.form["password"]), "viewer", now()))
                db.commit()
                start_session(db.execute("SELECT * FROM users WHERE id=?", (cur.lastrowid,)).fetchone())
                flash("Welcome! Your account has read-only access. An admin can upgrade your role.", "success")
                return redirect(url_for("dashboard"))
            except sqlite3.IntegrityError:
                flash("That username is already taken.", "error")
    return render_template("register.html")


@app.route("/logout", methods=["POST"])
def logout():
    session.clear()
    return redirect(url_for("login"))


# ---------------------------------------------------------------- pages
@app.route("/")
@needs()
def dashboard():
    products = all_products()
    low = [p for p in products if p["status"] == "low"]
    out = [p for p in products if p["status"] == "out"]
    ok = [p for p in products if p["status"] == "ok"]
    cats = {}
    for p in products:
        c = cats.setdefault(p["category"], {"ok": 0, "low": 0, "out": 0})
        c[p["status"]] += 1
    critical = sorted([p for p in products if p["status"] != "ok"],
                      key=lambda p: (p["status"] != "out", p["quantity"] - p["min_level"]))[:6]
    recent = get_db().execute("SELECT * FROM movements ORDER BY id DESC LIMIT 7").fetchall()
    stats = {
        "total": len(products), "low": len(low), "out": len(out), "ok": len(ok),
        "value": round(sum(p["value"] for p in products), 2),
        "restock_cost": round(sum(p["cost"] for p in products), 2),
    }
    health = round(len(ok) / len(products) * 100) if products else 100
    return render_template("dashboard.html", stats=stats, health=health, critical=critical,
                           recent=recent, cats=cats, page="dashboard")


@app.route("/inventory")
@needs()
def inventory():
    products = all_products()
    categories = sorted({p["category"] for p in products})
    suppliers = sorted({p["supplier"] for p in products if p["supplier"]})
    return render_template("inventory.html", products=products, categories=categories,
                           suppliers=suppliers, page="inventory")


@app.route("/history")
@needs()
def history():
    rows = get_db().execute("SELECT * FROM movements ORDER BY id DESC LIMIT 300").fetchall()
    return render_template("history.html", rows=rows, page="history")


@app.route("/restock")
@needs()
def restock():
    open_ids = on_order_ids()
    items = [p for p in all_products() if p["status"] != "ok"]
    for p in items:
        p["on_order"] = p["id"] in open_ids
    items.sort(key=lambda p: (p["supplier"] or "~", p["status"] != "out", p["name"]))
    groups = {}
    for p in items:
        groups.setdefault(p["supplier"] or "No supplier", []).append(p)
    total = round(sum(p["cost"] for p in items), 2)
    return render_template("restock.html", groups=groups, items=items, total=total,
                           generated=now(), page="restock")


# ---------------------------------------------------------------- products
def product_form():
    f = request.form
    name = f.get("name", "").strip()
    if not name:
        return None, "Product name is required."
    sku = f.get("sku", "").strip() or None
    return {
        "name": name[:120], "sku": sku[:40] if sku else None,
        "category": (f.get("category", "").strip() or "General")[:60],
        "supplier": f.get("supplier", "").strip()[:80],
        "unit": (f.get("unit", "").strip() or "pcs")[:20],
        "quantity": to_int(f.get("quantity")), "min_level": to_int(f.get("min_level")),
        "price": to_float(f.get("price")),
    }, None


@app.route("/products/add", methods=["POST"])
@needs("edit")
def add_product():
    data, err = product_form()
    if err:
        flash(err, "error")
        return redirect(url_for("inventory"))
    db = get_db()
    try:
        cur = db.execute(
            "INSERT INTO products (sku,name,category,supplier,unit,quantity,min_level,price,created_at,updated_at)"
            " VALUES (:sku,:name,:category,:supplier,:unit,:quantity,:min_level,:price,:t,:t)",
            {**data, "t": now()})
        log_move(db, cur.lastrowid, data["name"], data["quantity"], data["quantity"], "Product created")
        db.commit()
        flash(f"Added {data['name']}.", "success")
    except sqlite3.IntegrityError:
        flash("That SKU already exists.", "error")
    return redirect(url_for("inventory"))


@app.route("/products/<int:pid>/edit", methods=["POST"])
@needs("edit")
def edit_product(pid):
    data, err = product_form()
    if err:
        flash(err, "error")
        return redirect(url_for("inventory"))
    db = get_db()
    old = db.execute("SELECT * FROM products WHERE id=?", (pid,)).fetchone()
    if not old:
        abort(404)
    try:
        db.execute(
            "UPDATE products SET sku=:sku,name=:name,category=:category,supplier=:supplier,unit=:unit,"
            "quantity=:quantity,min_level=:min_level,price=:price,updated_at=:t WHERE id=:id",
            {**data, "t": now(), "id": pid})
        if data["quantity"] != old["quantity"]:
            log_move(db, pid, data["name"], data["quantity"] - old["quantity"], data["quantity"], "Manual edit")
        db.commit()
        flash(f"Updated {data['name']}.", "success")
    except sqlite3.IntegrityError:
        flash("That SKU already exists.", "error")
    return redirect(url_for("inventory"))


@app.route("/products/<int:pid>/delete", methods=["POST"])
@needs("delete")
def delete_product(pid):
    db = get_db()
    p = db.execute("SELECT name FROM products WHERE id=?", (pid,)).fetchone()
    if p:
        db.execute("DELETE FROM products WHERE id=?", (pid,))
        log_move(db, None, p["name"], 0, 0, "Product deleted")
        db.commit()
        flash(f"Deleted {p['name']}.", "success")
    return redirect(url_for("inventory"))


@app.route("/products/<int:pid>/adjust", methods=["POST"])
@needs("use")
def adjust(pid):
    payload = request.get_json(silent=True) or {}
    delta = to_int(payload.get("delta"), 0, minimum=-100000)
    if delta > 0 and not can("edit"):
        return jsonify(error="Your role can only decrease stock."), 403
    reason = str(payload.get("reason") or ("Stock added" if delta > 0 else "Stock used"))[:80]
    db = get_db()
    row = db.execute("SELECT * FROM products WHERE id=?", (pid,)).fetchone()
    if not row:
        return jsonify(error="not found"), 404
    if delta == 0:
        return jsonify(error="delta must not be 0"), 400
    new_qty = max(row["quantity"] + delta, 0)
    applied = new_qty - row["quantity"]
    db.execute("UPDATE products SET quantity=?, updated_at=? WHERE id=?", (new_qty, now(), pid))
    log_move(db, pid, row["name"], applied, new_qty, reason)
    db.commit()
    p = enrich({**dict(row), "quantity": new_qty})
    if status_of(row["quantity"], row["min_level"]) == "ok" and p["status"] != "ok":
        send_telegram(alert_text([p]))  # auto alert when an item newly drops
    return jsonify(id=pid, quantity=new_qty, status=p["status"], pct=p["pct"],
                   reorder=p["reorder"], value=p["value"])


@app.route("/products/import", methods=["POST"])
@needs("edit")
def import_csv():
    f = request.files.get("file")
    if not f or not f.filename.lower().endswith(".csv"):
        flash("Please choose a .csv file.", "error")
        return redirect(url_for("inventory"))
    try:
        text = f.read().decode("utf-8-sig")
        reader = csv.DictReader(io.StringIO(text))
        db, added, updated = get_db(), 0, 0
        for r in reader:
            r = {(k or "").strip().lower(): (v or "").strip() for k, v in r.items()}
            name = r.get("name")
            if not name:
                continue
            vals = {"sku": r.get("sku") or None, "name": name[:120],
                    "category": (r.get("category") or "General")[:60],
                    "supplier": r.get("supplier", "")[:80], "unit": (r.get("unit") or "pcs")[:20],
                    "quantity": to_int(r.get("quantity")), "min_level": to_int(r.get("min_level")),
                    "price": to_float(r.get("price")), "t": now()}
            existing = db.execute("SELECT * FROM products WHERE sku=?", (vals["sku"],)).fetchone() if vals["sku"] else None
            if existing:
                db.execute("UPDATE products SET name=:name,category=:category,supplier=:supplier,unit=:unit,"
                           "quantity=:quantity,min_level=:min_level,price=:price,updated_at=:t WHERE sku=:sku", vals)
                if vals["quantity"] != existing["quantity"]:
                    log_move(db, existing["id"], name, vals["quantity"] - existing["quantity"], vals["quantity"], "CSV import")
                updated += 1
            else:
                cur = db.execute(
                    "INSERT INTO products (sku,name,category,supplier,unit,quantity,min_level,price,created_at,updated_at)"
                    " VALUES (:sku,:name,:category,:supplier,:unit,:quantity,:min_level,:price,:t,:t)", vals)
                log_move(db, cur.lastrowid, name, vals["quantity"], vals["quantity"], "CSV import")
                added += 1
        db.commit()
        flash(f"Import complete: {added} added, {updated} updated.", "success")
    except Exception as exc:
        flash(f"Import failed: {exc}", "error")
    return redirect(url_for("inventory"))


@app.route("/seed", methods=["POST"])
@needs("edit")
def seed():
    db = get_db()
    n = 0
    for name, sku, cat, sup, unit, qty, mn, price in DEMO:
        try:
            cur = db.execute(
                "INSERT INTO products (sku,name,category,supplier,unit,quantity,min_level,price,created_at,updated_at)"
                " VALUES (?,?,?,?,?,?,?,?,?,?)", (sku, name, cat, sup, unit, qty, mn, price, now(), now()))
            log_move(db, cur.lastrowid, name, qty, qty, "Demo data")
            n += 1
        except sqlite3.IntegrityError:
            pass
    db.commit()
    flash(f"Loaded {n} demo products.", "success")
    return redirect(url_for("dashboard"))


@app.route("/alerts/send", methods=["POST"])
@needs("edit")
def send_alerts():
    items = [p for p in all_products() if p["status"] != "ok"]
    if not items:
        flash("Nothing is low on stock. No alert needed.", "success")
    else:
        ok, msg = send_telegram(alert_text(items))
        flash(msg, "success" if ok else "error")
    return redirect(request.referrer or url_for("dashboard"))


# ---------------------------------------------------------------- restock orders
@app.route("/orders")
@needs("orders")
def orders():
    db = get_db()
    rows = db.execute("SELECT * FROM orders ORDER BY (status='ordered') DESC, id DESC LIMIT 100").fetchall()
    result = []
    for o in rows:
        items = db.execute("SELECT * FROM order_items WHERE order_id=?", (o["id"],)).fetchall()
        total = round(sum(i["qty"] * i["unit_price"] for i in items), 2)
        result.append({**dict(o), "items": items, "total": total})
    return render_template("orders.html", orders=result, page="orders")


@app.route("/orders/create", methods=["POST"])
@needs("orders")
def create_order():
    supplier = request.form.get("supplier", "").strip()
    open_ids = on_order_ids()
    items = [p for p in all_products()
             if p["status"] != "ok" and p["supplier"] == supplier and p["id"] not in open_ids]
    if not items:
        flash("Nothing new to order for this supplier.", "error")
        return redirect(url_for("restock"))
    db = get_db()
    cur = db.execute("INSERT INTO orders (supplier,status,created_by,created_at) VALUES (?,?,?,?)",
                     (supplier, "ordered", actor(), now()))
    for p in items:
        db.execute("INSERT INTO order_items (order_id,product_id,product_name,unit,qty,unit_price) VALUES (?,?,?,?,?,?)",
                   (cur.lastrowid, p["id"], p["name"], p["unit"], p["reorder"], p["price"]))
    db.commit()
    flash(f"Order #{cur.lastrowid} created with {len(items)} item(s).", "success")
    return redirect(url_for("orders"))


@app.route("/orders/<int:oid>/receive", methods=["POST"])
@needs("orders")
def receive_order(oid):
    db = get_db()
    o = db.execute("SELECT * FROM orders WHERE id=?", (oid,)).fetchone()
    if not o or o["status"] != "ordered":
        flash("That order is not open.", "error")
        return redirect(url_for("orders"))
    for i in db.execute("SELECT * FROM order_items WHERE order_id=?", (oid,)).fetchall():
        p = db.execute("SELECT * FROM products WHERE id=?", (i["product_id"],)).fetchone()
        if p:
            new_qty = p["quantity"] + i["qty"]
            db.execute("UPDATE products SET quantity=?, updated_at=? WHERE id=?", (new_qty, now(), p["id"]))
            log_move(db, p["id"], p["name"], i["qty"], new_qty, f"Order #{oid} received")
    db.execute("UPDATE orders SET status='received', closed_by=?, closed_at=? WHERE id=?", (actor(), now(), oid))
    db.commit()
    flash(f"Order #{oid} received. Stock has been updated.", "success")
    return redirect(url_for("orders"))


@app.route("/orders/<int:oid>/cancel", methods=["POST"])
@needs("orders")
def cancel_order(oid):
    db = get_db()
    db.execute("UPDATE orders SET status='cancelled', closed_by=?, closed_at=? WHERE id=? AND status='ordered'",
               (actor(), now(), oid))
    db.commit()
    flash(f"Order #{oid} cancelled.", "success")
    return redirect(url_for("orders"))


# ---------------------------------------------------------------- team (admin)
@app.route("/users")
@needs("users")
def users():
    rows = get_db().execute("SELECT * FROM users ORDER BY (role='admin') DESC, username COLLATE NOCASE").fetchall()
    return render_template("users.html", rows=rows, demo_password=DEMO_PASSWORD, page="users")


@app.route("/users/add", methods=["POST"])
@needs("users")
def add_user():
    u = request.form.get("username", "").strip()
    role = request.form.get("role", "viewer")
    err = check_new_credentials(u, request.form.get("password", ""))
    if role not in ROLES:
        err = "Unknown role."
    if err:
        flash(err, "error")
        return redirect(url_for("users"))
    try:
        db = get_db()
        db.execute("INSERT INTO users (username,password_hash,role,created_at) VALUES (?,?,?,?)",
                   (u, generate_password_hash(request.form["password"]), role, now()))
        db.commit()
        flash(f"User {u} created as {role}.", "success")
    except sqlite3.IntegrityError:
        flash("That username is already taken.", "error")
    return redirect(url_for("users"))


@app.route("/users/demo", methods=["POST"])
@needs("users")
def demo_team():
    db, n = get_db(), 0
    for name, role in DEMO_TEAM:
        try:
            db.execute("INSERT INTO users (username,password_hash,role,created_at) VALUES (?,?,?,?)",
                       (name, generate_password_hash(DEMO_PASSWORD), role, now()))
            n += 1
        except sqlite3.IntegrityError:
            pass
    db.commit()
    flash(f"Added {n} demo user(s) with password {DEMO_PASSWORD}. Delete them before going public.", "success")
    return redirect(url_for("users"))


def target_user(uid):
    row = get_db().execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()
    if not row:
        abort(404)
    return row


@app.route("/users/<int:uid>/role", methods=["POST"])
@needs("users")
def set_role(uid):
    row, role = target_user(uid), request.form.get("role", "")
    if row["id"] == g.user["id"]:
        flash("You cannot change your own role.", "error")
    elif role not in ROLES:
        flash("Unknown role.", "error")
    else:
        get_db().execute("UPDATE users SET role=? WHERE id=?", (role, uid))
        get_db().commit()
        flash(f"{row['username']} is now {role}.", "success")
    return redirect(url_for("users"))


@app.route("/users/<int:uid>/toggle", methods=["POST"])
@needs("users")
def toggle_user(uid):
    row = target_user(uid)
    if row["id"] == g.user["id"]:
        flash("You cannot disable your own account.", "error")
    else:
        get_db().execute("UPDATE users SET active=? WHERE id=?", (0 if row["active"] else 1, uid))
        get_db().commit()
        flash(f"{row['username']} {'disabled' if row['active'] else 'enabled'}.", "success")
    return redirect(url_for("users"))


@app.route("/users/<int:uid>/password", methods=["POST"])
@needs("users")
def reset_password(uid):
    row, pw = target_user(uid), request.form.get("password", "")
    if len(pw) < 8:
        flash("Password must be at least 8 characters.", "error")
    else:
        get_db().execute("UPDATE users SET password_hash=? WHERE id=?", (generate_password_hash(pw), uid))
        get_db().commit()
        flash(f"Password reset for {row['username']}.", "success")
    return redirect(url_for("users"))


@app.route("/users/<int:uid>/delete", methods=["POST"])
@needs("users")
def delete_user(uid):
    row = target_user(uid)
    if row["id"] == g.user["id"]:
        flash("You cannot delete your own account.", "error")
    else:
        get_db().execute("DELETE FROM users WHERE id=?", (uid,))
        get_db().commit()
        flash(f"Deleted user {row['username']}.", "success")
    return redirect(url_for("users"))


@app.route("/account", methods=["GET", "POST"])
@needs()
def account():
    if request.method == "POST":
        row = get_db().execute("SELECT * FROM users WHERE id=?", (g.user["id"],)).fetchone()
        new = request.form.get("new", "")
        if not check_password_hash(row["password_hash"], request.form.get("current", "")):
            flash("Current password is incorrect.", "error")
        elif len(new) < 8:
            flash("New password must be at least 8 characters.", "error")
        elif new != request.form.get("confirm", ""):
            flash("New passwords do not match.", "error")
        else:
            get_db().execute("UPDATE users SET password_hash=? WHERE id=?", (generate_password_hash(new), row["id"]))
            get_db().commit()
            flash("Password updated.", "success")
        return redirect(url_for("account"))
    mine = get_db().execute("SELECT * FROM movements WHERE user=? ORDER BY id DESC LIMIT 8", (g.user["username"],)).fetchall()
    return render_template("account.html", mine=mine, page="account")


# ---------------------------------------------------------------- exports
@app.route("/restock.csv")
@needs()
def restock_csv():
    items = [p for p in all_products() if p["status"] != "ok"]
    items.sort(key=lambda p: (p["supplier"] or "~", p["name"]))
    rows = [(p["name"], p["sku"] or "", p["category"], p["supplier"], p["status"].upper(), p["quantity"],
             p["min_level"], p["reorder"], p["unit"], p["price"], p["cost"]) for p in items]
    return csv_response(f"restock-list-{datetime.now():%Y%m%d}.csv",
                        ["Product", "SKU", "Category", "Supplier", "Status", "Current", "Minimum",
                         "Order Qty", "Unit", "Unit Price", "Est. Cost"], rows)


@app.route("/inventory.csv")
@needs()
def inventory_csv():
    rows = [(p["name"], p["sku"] or "", p["category"], p["supplier"], p["unit"], p["quantity"],
             p["min_level"], p["price"]) for p in all_products()]
    return csv_response(f"inventory-{datetime.now():%Y%m%d}.csv",
                        ["name", "sku", "category", "supplier", "unit", "quantity", "min_level", "price"], rows)


# ---------------------------------------------------------------- API / health
@app.route("/api/stats")
@needs()
def api_stats():
    ps = all_products()
    return jsonify(total=len(ps), low=sum(p["status"] == "low" for p in ps),
                   out=sum(p["status"] == "out" for p in ps),
                   value=round(sum(p["value"] for p in ps), 2))


@app.route("/health")
def health():
    try:
        get_db().execute("SELECT 1")
        return jsonify(status="ok", time=now())
    except Exception as exc:
        return jsonify(status="error", detail=str(exc)), 500


@app.template_filter("money")
def money(v):
    return f"₹{v:,.0f}" if float(v).is_integer() else f"₹{v:,.2f}"


@app.template_filter("ago")
def ago(ts):
    try:
        d = datetime.now() - datetime.strptime(ts, "%Y-%m-%d %H:%M:%S")
    except (ValueError, TypeError):
        return ts or "never"
    s = int(d.total_seconds())
    if s < 60:
        return "just now"
    if s < 3600:
        return f"{s // 60}m ago"
    if s < 86400:
        return f"{s // 3600}h ago"
    return f"{d.days}d ago"


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)),
            debug=os.environ.get("FLASK_DEBUG") == "1")

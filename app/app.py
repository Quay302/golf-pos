# =============================================================
# Golf POS — Proprietary Software
# Copyright (c) 2025 Ashton Collins. All rights reserved.
#
# Unauthorized copying, modification, distribution or use
# of this software, in whole or in part, is strictly
# prohibited without prior written permission.
# =============================================================
import os
import sqlite3
import stripe
from datetime import datetime, timedelta
from flask import Flask, request, jsonify, send_from_directory, session
from functools import wraps
from flask_cors import CORS
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)

CORS(app, origins=[os.getenv("ALLOWED_ORIGIN", "https://acwebsite.click")])

app.secret_key = os.getenv("FLASK_SECRET_KEY")
stripe.api_key = os.getenv("STRIPE_SECRET_KEY")
endpoint_secret = os.getenv("STRIPE_WEBHOOK_SECRET")

app.config.update(
    SESSION_COOKIE_SECURE=True,
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE='Lax',
    PERMANENT_SESSION_LIFETIME=timedelta(hours=8),
    SESSION_COOKIE_DOMAIN=None
)


# -------------------------
# DATABASE
# -------------------------
def init_db():
    conn = sqlite3.connect("payments.db")
    c = conn.cursor()

    c.execute("""
        CREATE TABLE IF NOT EXISTS orders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            order_number TEXT,
            stripe_session_id TEXT UNIQUE,
            amount REAL,
            discount_amount REAL DEFAULT 0,
            items TEXT,
            method TEXT,
            status TEXT,
            created_at TEXT
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS products (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            category TEXT,
            name TEXT,
            price REAL,
            active INTEGER DEFAULT 1
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS discount_codes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            code TEXT UNIQUE,
            type TEXT,
            value REAL,
            active INTEGER DEFAULT 1
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS tee_sheet (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date TEXT,
            time TEXT,
            player_name TEXT,
            num_players INTEGER DEFAULT 1,
            holes INTEGER,
            cart INTEGER DEFAULT 0,
            status TEXT DEFAULT 'booked',
            created_at TEXT
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS tee_sheet_settings (
            id INTEGER PRIMARY KEY,
            open_time TEXT DEFAULT '07:00',
            close_time TEXT DEFAULT '18:00',
            interval_minutes INTEGER DEFAULT 10
        )
    """)

    # Seed default products if empty
    c.execute("SELECT COUNT(*) FROM products")
    if c.fetchone()[0] == 0:
        defaults = [
            ("tees", "9 Holes Walking", 40),
            ("tees", "9 Holes Cart", 55),
            ("tees", "18 Holes Walking", 70),
            ("tees", "18 Holes Cart", 85),
            ("balls", "Titleist Pro V1", 55),
            ("balls", "Callaway Chrome Soft", 50),
            ("balls", "TaylorMade TP5", 52),
            ("drinks", "Beer", 8),
            ("drinks", "Soda", 3),
            ("drinks", "Seltzer", 6),
            ("snacks", "Protein Bar", 5),
            ("snacks", "Chex Mix", 4),
            ("snacks", "Fruit Cup", 3),
        ]
        c.executemany(
            "INSERT INTO products (category, name, price) VALUES (?, ?, ?)",
            defaults
        )

    # Seed default tee sheet settings if empty
    c.execute("SELECT COUNT(*) FROM tee_sheet_settings")
    if c.fetchone()[0] == 0:
        c.execute(
            "INSERT INTO tee_sheet_settings (id, open_time, close_time, interval_minutes) VALUES (1, '07:00', '18:00', 10)"
        )

    conn.commit()
    conn.close()

init_db()


# -------------------------
# DECORATORS
# -------------------------
def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get("user"):
            return jsonify({"error": "unauthorized"}), 401
        return f(*args, **kwargs)
    return decorated


def manager_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get("user"):
            return jsonify({"error": "unauthorized"}), 401
        if session.get("role") != "manager":
            return jsonify({"error": "manager access required"}), 403
        return f(*args, **kwargs)
    return decorated


# -------------------------
# AUTH
# -------------------------
STAFF_USERS = {
    os.getenv("STAFF_USER_1"): os.getenv("STAFF_PASS_1"),
    os.getenv("STAFF_USER_2"): os.getenv("STAFF_PASS_2"),
    os.getenv("MANAGER_USER"): os.getenv("MANAGER_PASS"),
}

@app.route("/login", methods=["POST"])
def login():
    data = request.json
    username = data.get("username", "").strip()
    password = data.get("password", "")

    if STAFF_USERS.get(username) == password and password != "":
        session.permanent = True
        session["user"] = username
        role = "manager" if username == os.getenv("MANAGER_USER") else "staff"
        session["role"] = role
        return jsonify({"username": username, "role": role})

    return jsonify({"error": "invalid credentials"}), 401


@app.route("/logout", methods=["POST"])
def logout():
    session.clear()
    return jsonify({"status": "logged out"})


# -------------------------
# SERVE FRONTEND
# -------------------------
@app.route("/")
def index():
    return send_from_directory("static", "index.html")


# -------------------------
# PRODUCTS
# -------------------------
@app.route("/products", methods=["GET"])
@login_required
def get_products():
    conn = sqlite3.connect("payments.db")
    c = conn.cursor()
    c.execute("SELECT id, category, name, price FROM products WHERE active=1 ORDER BY category, name")
    rows = c.fetchall()
    conn.close()

    products = {}
    for row in rows:
        cat = row[1]
        if cat not in products:
            products[cat] = []
        products[cat].append({"id": row[0], "name": row[2], "price": row[3]})

    return jsonify(products)


@app.route("/products", methods=["POST"])
@manager_required
def add_product():
    data = request.json
    category = data.get("category", "").strip()
    name = data.get("name", "").strip()
    price = data.get("price")

    if not category or not name or price is None:
        return jsonify({"error": "category, name and price required"}), 400

    conn = sqlite3.connect("payments.db")
    c = conn.cursor()
    c.execute(
        "INSERT INTO products (category, name, price) VALUES (?, ?, ?)",
        (category, name, float(price))
    )
    new_id = c.lastrowid
    conn.commit()
    conn.close()

    return jsonify({"id": new_id, "category": category, "name": name, "price": price})


@app.route("/products/<int:product_id>", methods=["PUT"])
@manager_required
def update_product(product_id):
    data = request.json
    name = data.get("name", "").strip()
    price = data.get("price")
    category = data.get("category", "").strip()

    if not name or price is None or not category:
        return jsonify({"error": "category, name and price required"}), 400

    conn = sqlite3.connect("payments.db")
    c = conn.cursor()
    c.execute(
        "UPDATE products SET name=?, price=?, category=? WHERE id=?",
        (name, float(price), category, product_id)
    )
    conn.commit()
    conn.close()

    return jsonify({"status": "updated"})


@app.route("/products/<int:product_id>", methods=["DELETE"])
@manager_required
def delete_product(product_id):
    conn = sqlite3.connect("payments.db")
    c = conn.cursor()
    c.execute("UPDATE products SET active=0 WHERE id=?", (product_id,))
    conn.commit()
    conn.close()
    return jsonify({"status": "deleted"})


# -------------------------
# DISCOUNT CODES
# -------------------------
@app.route("/discount-codes", methods=["GET"])
@manager_required
def get_discount_codes():
    conn = sqlite3.connect("payments.db")
    c = conn.cursor()
    c.execute("SELECT id, code, type, value, active FROM discount_codes ORDER BY id DESC")
    rows = c.fetchall()
    conn.close()
    return jsonify([
        {"id": r[0], "code": r[1], "type": r[2], "value": r[3], "active": bool(r[4])}
        for r in rows
    ])


@app.route("/discount-codes", methods=["POST"])
@manager_required
def add_discount_code():
    data = request.json
    code = data.get("code", "").strip().upper()
    dtype = data.get("type", "")
    value = data.get("value")

    if not code or dtype not in ("percent", "fixed") or value is None:
        return jsonify({"error": "code, type (percent/fixed) and value required"}), 400

    try:
        conn = sqlite3.connect("payments.db")
        c = conn.cursor()
        c.execute(
            "INSERT INTO discount_codes (code, type, value) VALUES (?, ?, ?)",
            (code, dtype, float(value))
        )
        new_id = c.lastrowid
        conn.commit()
        conn.close()
        return jsonify({"id": new_id, "code": code, "type": dtype, "value": value, "active": True})
    except sqlite3.IntegrityError:
        return jsonify({"error": "code already exists"}), 409


@app.route("/discount-codes/<int:code_id>/toggle", methods=["PUT"])
@manager_required
def toggle_discount_code(code_id):
    conn = sqlite3.connect("payments.db")
    c = conn.cursor()
    c.execute("UPDATE discount_codes SET active = 1 - active WHERE id=?", (code_id,))
    conn.commit()
    conn.close()
    return jsonify({"status": "toggled"})


@app.route("/discount/validate", methods=["POST"])
@login_required
def validate_discount():
    data = request.json
    code = data.get("code", "").strip().upper()
    subtotal = data.get("subtotal", 0)

    conn = sqlite3.connect("payments.db")
    c = conn.cursor()
    c.execute(
        "SELECT type, value FROM discount_codes WHERE code=? AND active=1",
        (code,)
    )
    row = c.fetchone()
    conn.close()

    if not row:
        return jsonify({"error": "invalid or inactive code"}), 404

    dtype, value = row
    if dtype == "percent":
        discount = round(subtotal * (value / 100), 2)
        label = f"{int(value)}% off"
    else:
        discount = min(float(value), subtotal)
        label = f"${value:.2f} off"

    return jsonify({"type": dtype, "value": value, "discount": discount, "label": label})


# -------------------------
# STRIPE TERMINAL
# -------------------------
@app.route("/terminal/connection-token", methods=["POST"])
@login_required
def connection_token():
    token = stripe.terminal.ConnectionToken.create()
    return jsonify({"secret": token.secret})


@app.route("/terminal/create-payment-intent", methods=["POST"])
@login_required
def create_payment_intent():
    data = request.json
    items = data.get("items", [])
    discount_amount = data.get("discount_amount", 0)

    if not items:
        return jsonify({"error": "empty cart"}), 400

    subtotal = sum(item["price"] * item.get("quantity", 1) for item in items)
    total = max(0, subtotal - discount_amount)
    amount = int(round(total * 100))

    if amount < 50:
        return jsonify({"error": "amount too small"}), 400

    intent = stripe.PaymentIntent.create(
        amount=amount,
        currency="usd",
        payment_method_types=["card_present"],
        capture_method="automatic",
    )

    return jsonify({"client_secret": intent.client_secret, "amount": amount})


# -------------------------
# STRIPE PAYMENT LINK
# -------------------------
@app.route("/pay/link", methods=["POST"])
@login_required
def pay_link():
    data = request.json
    items = data.get("items", [])
    discount_amount = data.get("discount_amount", 0)

    if not items:
        return jsonify({"error": "empty cart"}), 400

    line_items = []
    for item in items:
        qty = item.get("quantity", 1)
        line_items.append({
            "price_data": {
                "currency": "usd",
                "product_data": {"name": item["name"]},
                "unit_amount": int(item["price"] * 100)
            },
            "quantity": qty
        })

    if discount_amount > 0:
        line_items.append({
            "price_data": {
                "currency": "usd",
                "product_data": {"name": "Discount"},
                "unit_amount": -int(discount_amount * 100)
            },
            "quantity": 1
        })

    checkout_session = stripe.checkout.Session.create(
        mode="payment",
        line_items=line_items,
        success_url=os.getenv("SUCCESS_URL", "https://acwebsite.click/?success=true"),
        cancel_url=os.getenv("CANCEL_URL", "https://acwebsite.click/?cancelled=true")
    )

    return jsonify({"url": checkout_session.url})


# -------------------------
# HELPERS
# -------------------------
def generate_order_number(conn):
    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM orders")
    count = c.fetchone()[0]
    return f"ORD-{count + 1:04d}"


def save_order(stripe_id, amount, discount_amount, items_str, method, status="paid"):
    conn = sqlite3.connect("payments.db")
    c = conn.cursor()
    order_number = generate_order_number(conn)
    c.execute("""
        INSERT OR IGNORE INTO orders
            (order_number, stripe_session_id, amount, discount_amount, items, method, status, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        order_number,
        stripe_id,
        amount,
        discount_amount,
        items_str,
        method,
        status,
        datetime.utcnow().isoformat()
    ))
    conn.commit()
    conn.close()
    print(f"ORDER SAVED [{method}] {order_number}:", stripe_id)


# -------------------------
# CASH PAYMENT
# -------------------------
@app.route("/cash/complete", methods=["POST"])
@login_required
def cash_complete():
    data = request.json
    total = data.get("total", 0)
    tendered = data.get("tendered", 0)
    discount_amount = data.get("discount_amount", 0)

    change = round(tendered - total, 2)

    if change < 0:
        return jsonify({"error": "insufficient amount"}), 400

    save_order(
        f"CASH-{datetime.utcnow().strftime('%Y%m%d%H%M%S')}",
        total,
        discount_amount,
        "cash",
        "cash"
    )

    return jsonify({"change": change})


# -------------------------
# TEE SHEET
# -------------------------
@app.route("/teesheet", methods=["GET"])
@login_required
def get_teesheet():
    date = request.args.get("date", datetime.utcnow().strftime("%Y-%m-%d"))

    conn = sqlite3.connect("payments.db")
    c = conn.cursor()

    # Get settings
    c.execute("SELECT open_time, close_time, interval_minutes FROM tee_sheet_settings WHERE id=1")
    row = c.fetchone()
    open_time, close_time, interval = row if row else ("07:00", "18:00", 10)

    # Get all bookings for this date (excluding cancelled so slots reopen)
    c.execute("""
        SELECT id, time, player_name, num_players, holes, cart, status
        FROM tee_sheet
        WHERE date=? AND status != 'cancelled'
    """, (date,))
    bookings = {}
    for r in c.fetchall():
        bookings[r[1]] = {
            "id": r[0],
            "player_name": r[2],
            "num_players": r[3],
            "holes": r[4],
            "cart": bool(r[5]),
            "status": r[6]
        }
    conn.close()

    # Generate time slots
    open_h, open_m = map(int, open_time.split(":"))
    close_h, close_m = map(int, close_time.split(":"))

    base = datetime.now().replace(second=0, microsecond=0)
    current = base.replace(hour=open_h, minute=open_m)
    close_dt = base.replace(hour=close_h, minute=close_m)

    slots = []
    while current <= close_dt:
        time_str = current.strftime("%H:%M")
        hour = current.hour % 12 or 12
        minute = current.strftime("%M")
        ampm = "AM" if current.hour < 12 else "PM"
        display_time = f"{hour}:{minute} {ampm}"

        slot = {"time": time_str, "display_time": display_time}
        if time_str in bookings:
            slot.update(bookings[time_str])
        else:
            slot["status"] = "available"
        slots.append(slot)
        current += timedelta(minutes=int(interval))

    return jsonify({
        "date": date,
        "slots": slots,
        "settings": {
            "open_time": open_time,
            "close_time": close_time,
            "interval_minutes": interval
        }
    })


@app.route("/teesheet/book", methods=["POST"])
@login_required
def book_tee_time():
    data = request.json
    date = data.get("date", "").strip()
    time = data.get("time", "").strip()
    player_name = data.get("player_name", "").strip()
    num_players = int(data.get("num_players", 1))
    holes = int(data.get("holes", 18))
    cart = bool(data.get("cart", False))

    if not date or not time or not player_name:
        return jsonify({"error": "date, time and player_name required"}), 400

    if holes not in (9, 18):
        return jsonify({"error": "holes must be 9 or 18"}), 400

    if not (1 <= num_players <= 4):
        return jsonify({"error": "num_players must be between 1 and 4"}), 400

    conn = sqlite3.connect("payments.db")
    c = conn.cursor()

    # Check if slot is already booked (cancelled slots free up the slot)
    c.execute(
        "SELECT id FROM tee_sheet WHERE date=? AND time=? AND status='booked'",
        (date, time)
    )
    if c.fetchone():
        conn.close()
        return jsonify({"error": "slot already booked"}), 409

    c.execute("""
        INSERT INTO tee_sheet (date, time, player_name, num_players, holes, cart, status, created_at)
        VALUES (?, ?, ?, ?, ?, ?, 'booked', ?)
    """, (date, time, player_name, num_players, holes, 1 if cart else 0, datetime.utcnow().isoformat()))

    new_id = c.lastrowid
    conn.commit()
    conn.close()

    return jsonify({"id": new_id, "status": "booked"})


@app.route("/teesheet/<int:booking_id>/checkin", methods=["PUT"])
@login_required
def checkin_tee_time(booking_id):
    conn = sqlite3.connect("payments.db")
    c = conn.cursor()

    c.execute(
        "SELECT holes, cart, num_players FROM tee_sheet WHERE id=? AND status='booked'",
        (booking_id,)
    )
    row = c.fetchone()

    if not row:
        conn.close()
        return jsonify({"error": "booking not found or already checked in"}), 404

    holes, cart, num_players = row

    # Build product name matching the seeded defaults
    product_name = f"{holes} Holes {'Cart' if cart else 'Walking'}"

    # Look up price — fall back gracefully if product was renamed
    c.execute(
        "SELECT name, price FROM products WHERE name=? AND category='tees' AND active=1",
        (product_name,)
    )
    product = c.fetchone()

    # Mark checked in
    c.execute("UPDATE tee_sheet SET status='checked_in' WHERE id=?", (booking_id,))
    conn.commit()
    conn.close()

    response = {"status": "checked_in", "num_players": num_players}
    if product:
        response["product"] = {"name": product[0], "price": product[1]}
    else:
        response["product"] = None

    return jsonify(response)


@app.route("/teesheet/<int:booking_id>/cancel", methods=["PUT"])
@login_required
def cancel_tee_time(booking_id):
    conn = sqlite3.connect("payments.db")
    c = conn.cursor()
    c.execute(
        "UPDATE tee_sheet SET status='cancelled' WHERE id=? AND status='booked'",
        (booking_id,)
    )
    affected = c.rowcount
    conn.commit()
    conn.close()

    if not affected:
        return jsonify({"error": "booking not found or already cancelled"}), 404

    return jsonify({"status": "cancelled"})


@app.route("/teesheet/settings", methods=["GET"])
@login_required
def get_teesheet_settings():
    conn = sqlite3.connect("payments.db")
    c = conn.cursor()
    c.execute("SELECT open_time, close_time, interval_minutes FROM tee_sheet_settings WHERE id=1")
    row = c.fetchone()
    conn.close()
    if row:
        return jsonify({"open_time": row[0], "close_time": row[1], "interval_minutes": row[2]})
    return jsonify({"open_time": "07:00", "close_time": "18:00", "interval_minutes": 10})


@app.route("/teesheet/settings", methods=["PUT"])
@manager_required
def update_teesheet_settings():
    data = request.json
    open_time = data.get("open_time", "07:00").strip()
    close_time = data.get("close_time", "18:00").strip()
    interval_minutes = int(data.get("interval_minutes", 10))

    if interval_minutes not in (8, 10, 12, 15):
        return jsonify({"error": "interval must be 8, 10, 12, or 15 minutes"}), 400

    conn = sqlite3.connect("payments.db")
    c = conn.cursor()
    c.execute("""
        INSERT OR REPLACE INTO tee_sheet_settings (id, open_time, close_time, interval_minutes)
        VALUES (1, ?, ?, ?)
    """, (open_time, close_time, interval_minutes))
    conn.commit()
    conn.close()

    return jsonify({"status": "updated"})


# -------------------------
# WEBHOOK
# -------------------------
@app.route("/webhook", methods=["POST"])
def webhook():
    payload = request.data
    sig_header = request.headers.get("Stripe-Signature")

    try:
        event = stripe.Webhook.construct_event(payload, sig_header, endpoint_secret)
    except Exception:
        return jsonify({"error": "invalid webhook"}), 400

    etype = event["type"]

    if etype == "payment_intent.succeeded":
        pi = event["data"]["object"]
        save_order(pi["id"], pi["amount"] / 100, 0, "terminal", "terminal")

    elif etype == "checkout.session.completed":
        cs = event["data"]["object"]
        save_order(cs["id"], cs["amount_total"] / 100, 0, "link", "link")

    elif etype == "payment_intent.payment_failed":
        pi = event["data"]["object"]
        reason = pi.get("last_payment_error", {}).get("message", "unknown")
        print(f"PAYMENT FAILED [{pi['id']}]: {reason}")

    elif etype == "checkout.session.expired":
        cs = event["data"]["object"]
        print(f"CHECKOUT EXPIRED [{cs['id']}]")

    elif etype == "charge.refunded":
        charge = event["data"]["object"]
        pi_id = charge.get("payment_intent")
        if pi_id:
            conn = sqlite3.connect("payments.db")
            c = conn.cursor()
            c.execute(
                "UPDATE orders SET status='refunded' WHERE stripe_session_id=?",
                (pi_id,)
            )
            conn.commit()
            conn.close()
            print(f"ORDER REFUNDED: {pi_id}")

    return jsonify({"status": "ok"})


# -------------------------
# ADMIN
# -------------------------
@app.route("/admin/orders")
@manager_required
def admin_orders():
    conn = sqlite3.connect("payments.db")
    c = conn.cursor()

    c.execute("SELECT * FROM orders ORDER BY id DESC")
    rows = c.fetchall()

    c.execute("""
        SELECT DATE(created_at) as day, COUNT(*), SUM(amount), method
        FROM orders
        WHERE status = 'paid'
        GROUP BY day, method
        ORDER BY day DESC
        LIMIT 14
    """)
    daily = c.fetchall()
    conn.close()

    total_revenue = sum(r[3] for r in rows if r[7] == "paid")

    html = """
    <html><head><style>
        body { font-family: Arial, sans-serif; padding: 20px; background: #f4f6f8; }
        h1 { color: #0b3d2e; }
        h2 { color: #0b3d2e; margin-top: 30px; }
        .order { background: white; border: 1px solid #dde1e7; padding: 12px;
                 margin: 8px 0; border-radius: 8px; }
        .badge { display: inline-block; padding: 2px 8px; border-radius: 10px;
                 font-size: 12px; font-weight: bold; }
        .paid { background: #d1fae5; color: #065f46; }
        .refunded { background: #fee2e2; color: #991b1b; }
        .terminal { background: #dbeafe; color: #1e40af; }
        .link { background: #fef3c7; color: #92400e; }
        .cash { background: #d1fae5; color: #065f46; }
        table { width: 100%%; border-collapse: collapse; background: white;
                border-radius: 8px; overflow: hidden; }
        th { background: #0b3d2e; color: white; padding: 10px; text-align: left; }
        td { padding: 10px; border-bottom: 1px solid #f0f0f0; }
        .revenue { font-size: 24px; font-weight: bold; color: #0b3d2e; }
    </style></head><body>
    <h1>POS Dashboard</h1>
    """

    html += f'<p class="revenue">Total Revenue: ${total_revenue:.2f}</p>'

    html += "<h2>Sales by Day</h2><table>"
    html += "<tr><th>Date</th><th>Orders</th><th>Revenue</th><th>Method</th></tr>"
    for d in daily:
        html += f"""<tr>
            <td>{d[0]}</td>
            <td>{d[1]}</td>
            <td>${d[2]:.2f}</td>
            <td><span class="badge {d[3]}">{d[3]}</span></td>
        </tr>"""
    html += "</table>"

    html += "<h2>All Orders</h2>"
    for r in rows:
        status_class = r[7] if r[7] in ("paid", "refunded") else "paid"
        method_class = r[6] if r[6] in ("terminal", "link", "cash") else "terminal"
        discount_line = f"<br><b>Discount:</b> -${r[4]:.2f}" if r[4] and r[4] > 0 else ""
        html += f"""
        <div class="order">
            <b>#{r[1]}</b>
            <span class="badge {method_class}">{r[6]}</span>
            <span class="badge {status_class}">{r[7]}</span><br>
            <b>Amount:</b> ${r[3]:.2f}{discount_line}<br>
            <b>Items:</b> {r[5]}<br>
            <b>Date:</b> {r[8]}
        </div>
        """

    html += "</body></html>"
    return html


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
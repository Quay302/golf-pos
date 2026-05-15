# =============================================================
# Golf POS — Proprietary Software
# Copyright (c) 2025 Ashton Collins. All rights reserved.
#
# Unauthorized copying, modification, distribution or use
# of this software, in whole or in part, is strictly
# prohibited without prior written permission.
# =============================================================
import os
import csv
import io
import json
import sqlite3
import stripe
from datetime import datetime, timedelta
from flask import Flask, request, jsonify, send_from_directory, session, Response
from functools import wraps
from flask_cors import CORS
from dotenv import load_dotenv

try:
    from sendgrid import SendGridAPIClient
    from sendgrid.mail import Mail
    SENDGRID_AVAILABLE = True
except ImportError:
    SENDGRID_AVAILABLE = False

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
            created_at TEXT,
            customer_email TEXT DEFAULT ''
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

    # Migrate: add customer_email to existing orders table if upgrading
    c.execute("PRAGMA table_info(orders)")
    order_cols = [row[1] for row in c.fetchall()]
    if "customer_email" not in order_cols:
        c.execute("ALTER TABLE orders ADD COLUMN customer_email TEXT DEFAULT ''")

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
# SENDGRID EMAIL
# -------------------------
def send_confirmation_email(order_number, amount, discount_amount, items_str, method, customer_email):
    """Send a receipt email via SendGrid. Fails silently so payments are never blocked."""
    if not customer_email or not SENDGRID_AVAILABLE:
        return
    api_key = os.getenv("SENDGRID_API_KEY")
    from_email = os.getenv("FROM_EMAIL", "receipts@acwebsite.click")
    course_name = os.getenv("COURSE_NAME", "Country Club")
    if not api_key:
        return

    try:
        try:
            items = json.loads(items_str)
            rows_html = ""
            for i in items:
                name = i.get("name") or i.get("n", "Item")
                price = float(i.get("price") or i.get("p", 0))
                qty = int(i.get("quantity") or i.get("q", 1))
                rows_html += f"""
                <tr>
                  <td style="padding:7px 0;font-size:14px;color:#1a1a1a;">{name}</td>
                  <td style="padding:7px 0;font-size:14px;color:#6b7280;text-align:center;">x{qty}</td>
                  <td style="padding:7px 0;font-size:14px;color:#1a1a1a;text-align:right;">${price * qty:.2f}</td>
                </tr>"""
        except Exception:
            rows_html = '<tr><td colspan="3" style="padding:7px 0;font-size:14px;color:#6b7280;">See staff for itemised receipt</td></tr>'

        discount_row = ""
        if discount_amount and float(discount_amount) > 0:
            discount_row = f"""
            <tr>
              <td colspan="2" style="padding:7px 0;font-size:13px;color:#065f46;">Discount applied</td>
              <td style="padding:7px 0;font-size:13px;color:#065f46;text-align:right;">-${float(discount_amount):.2f}</td>
            </tr>"""

        method_label = {
            "terminal": "Card — Tap to Pay",
            "link": "Online Payment Link",
            "cash": "Cash"
        }.get(method, method.title())

        now_str = datetime.utcnow().strftime("%B %d, %Y at %I:%M %p UTC")

        html = f"""<!DOCTYPE html>
<html>
<body style="margin:0;padding:0;background:#f4f6f8;font-family:Arial,sans-serif;">
  <div style="max-width:480px;margin:32px auto;border-radius:12px;overflow:hidden;box-shadow:0 4px 24px rgba(0,0,0,0.10);">
    <div style="background:#0b3d2e;padding:28px 24px;text-align:center;">
      <h1 style="color:white;margin:0;font-size:22px;font-weight:700;">{course_name}</h1>
      <p style="color:rgba(255,255,255,0.75);margin:6px 0 0;font-size:13px;">Payment Confirmation</p>
    </div>
    <div style="background:white;padding:28px 24px;">
      <p style="margin:0 0 4px;color:#6b7280;font-size:11px;text-transform:uppercase;letter-spacing:0.8px;">Order Number</p>
      <p style="margin:0 0 24px;color:#0b3d2e;font-size:22px;font-weight:700;">#{order_number}</p>
      <table style="width:100%;border-collapse:collapse;margin-bottom:20px;">
        <thead>
          <tr style="border-bottom:2px solid #f0f0f0;">
            <th style="text-align:left;padding:8px 0;font-size:11px;color:#6b7280;font-weight:600;text-transform:uppercase;">Item</th>
            <th style="text-align:center;padding:8px 0;font-size:11px;color:#6b7280;font-weight:600;text-transform:uppercase;">Qty</th>
            <th style="text-align:right;padding:8px 0;font-size:11px;color:#6b7280;font-weight:600;text-transform:uppercase;">Amount</th>
          </tr>
        </thead>
        <tbody>{rows_html}{discount_row}</tbody>
        <tfoot>
          <tr style="border-top:2px solid #f0f0f0;">
            <td colspan="2" style="padding:14px 0 0;font-size:16px;font-weight:700;color:#0b3d2e;">Total Paid</td>
            <td style="padding:14px 0 0;font-size:16px;font-weight:700;color:#0b3d2e;text-align:right;">${float(amount):.2f}</td>
          </tr>
        </tfoot>
      </table>
      <div style="background:#f4f6f8;border-radius:8px;padding:12px 16px;margin-bottom:24px;">
        <p style="margin:0;font-size:13px;color:#6b7280;">
          <span style="font-weight:600;color:#1a1a1a;">Method:</span> {method_label}
        </p>
        <p style="margin:4px 0 0;font-size:13px;color:#6b7280;">
          <span style="font-weight:600;color:#1a1a1a;">Date:</span> {now_str}
        </p>
      </div>
      <p style="margin:0;font-size:14px;color:#6b7280;text-align:center;line-height:1.6;">
        Thank you for visiting <strong style="color:#0b3d2e;">{course_name}</strong>.<br>
        We look forward to seeing you on the course!
      </p>
    </div>
    <div style="background:#f4f6f8;padding:14px 24px;text-align:center;">
      <p style="margin:0;font-size:11px;color:#9ca3af;">
        Powered by Collins Consulting · Golf Operations Technology
      </p>
    </div>
  </div>
</body>
</html>"""

        message = Mail(
            from_email=from_email,
            to_emails=customer_email,
            subject=f"Your receipt from {course_name} — #{order_number}",
            html_content=html
        )
        sg = SendGridAPIClient(api_key)
        sg.send(message)
        print(f"EMAIL SENT [{order_number}] → {customer_email}")

    except Exception as e:
        print(f"EMAIL ERROR [{order_number}]: {e}")


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
    customer_email = data.get("customer_email", "").strip()

    if not items:
        return jsonify({"error": "empty cart"}), 400

    subtotal = sum(item["price"] * item.get("quantity", 1) for item in items)
    total = max(0, subtotal - discount_amount)
    amount = int(round(total * 100))

    if amount < 50:
        return jsonify({"error": "amount too small"}), 400

    items_meta = json.dumps([
        {"n": i["name"][:40], "p": round(i["price"], 2), "q": i.get("quantity", 1)}
        for i in items
    ])[:490]

    intent = stripe.PaymentIntent.create(
        amount=amount,
        currency="usd",
        payment_method_types=["card_present"],
        capture_method="automatic",
        metadata={
            "customer_email": customer_email[:200],
            "items": items_meta,
            "discount_amount": str(round(discount_amount, 2))
        }
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
    customer_email = data.get("customer_email", "").strip()

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

    items_meta = json.dumps([
        {"n": i["name"][:40], "p": round(i["price"], 2), "q": i.get("quantity", 1)}
        for i in items
    ])[:490]

    checkout_session = stripe.checkout.Session.create(
        mode="payment",
        line_items=line_items,
        customer_email=customer_email if customer_email else None,
        success_url=os.getenv("SUCCESS_URL", "https://acwebsite.click/?success=true"),
        cancel_url=os.getenv("CANCEL_URL", "https://acwebsite.click/?cancelled=true"),
        metadata={
            "items": items_meta,
            "discount_amount": str(round(discount_amount, 2))
        }
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


def save_order(stripe_id, amount, discount_amount, items_str, method, status="paid", customer_email=""):
    conn = sqlite3.connect("payments.db")
    c = conn.cursor()
    order_number = generate_order_number(conn)
    c.execute("""
        INSERT OR IGNORE INTO orders
            (order_number, stripe_session_id, amount, discount_amount,
             items, method, status, created_at, customer_email)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        order_number,
        stripe_id,
        amount,
        discount_amount,
        items_str,
        method,
        status,
        datetime.utcnow().isoformat(),
        customer_email
    ))
    conn.commit()
    conn.close()
    print(f"ORDER SAVED [{method}] {order_number}:", stripe_id)
    return order_number


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
    customer_email = data.get("customer_email", "").strip()
    items = data.get("items", [])

    change = round(tendered - total, 2)

    if change < 0:
        return jsonify({"error": "insufficient amount"}), 400

    if items:
        items_str = json.dumps([
            {"n": i["name"][:40], "p": round(i["price"], 2), "q": i.get("quantity", 1)}
            for i in items
        ])
    else:
        items_str = "cash"

    order_number = save_order(
        f"CASH-{datetime.utcnow().strftime('%Y%m%d%H%M%S')}",
        total,
        discount_amount,
        items_str,
        "cash",
        customer_email=customer_email
    )

    if customer_email:
        send_confirmation_email(order_number, total, discount_amount, items_str, "cash", customer_email)

    return jsonify({"change": change, "order_number": order_number})


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
        # Use attribute access for new Stripe SDK compatibility
        meta = {k: v for k, v in pi.metadata.items()} if pi.metadata else {}
        customer_email = meta.get("customer_email", "")
        items_str = meta.get("items", "terminal")
        discount_amount = float(meta.get("discount_amount", 0) or 0)
        order_number = save_order(
            pi["id"], pi["amount"] / 100, discount_amount,
            items_str, "terminal", customer_email=customer_email
        )
        if customer_email:
            send_confirmation_email(
                order_number, pi["amount"] / 100,
                discount_amount, items_str, "terminal", customer_email
            )

    elif etype == "checkout.session.completed":
        cs = event["data"]["object"]
        meta = {k: v for k, v in cs.metadata.items()} if cs.metadata else {}
        # Stripe captures customer email on their checkout page
        customer_details = cs.customer_details
        customer_email = customer_details.email if customer_details else ""
        items_str = meta.get("items", "link")
        discount_amount = float(meta.get("discount_amount", 0) or 0)
        order_number = save_order(
            cs["id"], cs["amount_total"] / 100, discount_amount,
            items_str, "link", customer_email=customer_email
        )
        if customer_email:
            send_confirmation_email(
                order_number, cs["amount_total"] / 100,
                discount_amount, items_str, "link", customer_email
            )

    elif etype == "payment_intent.payment_failed":
        pi = event["data"]["object"]
        last_error = pi.last_payment_error
        reason = last_error.message if last_error else "unknown"
        print(f"PAYMENT FAILED [{pi['id']}]: {reason}")

    elif etype == "checkout.session.expired":
        cs = event["data"]["object"]
        print(f"CHECKOUT EXPIRED [{cs['id']}]")

    elif etype == "charge.refunded":
        charge = event["data"]["object"]
        pi_id = charge.payment_intent
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
# CSV EXPORT
# -------------------------
@app.route("/admin/export")
@manager_required
def export_csv():
    start = request.args.get("start", "").strip()
    end = request.args.get("end", "").strip()

    conn = sqlite3.connect("payments.db")
    c = conn.cursor()

    query = """
        SELECT order_number, created_at, amount, discount_amount,
               items, method, status, customer_email
        FROM orders
    """
    params = []
    conditions = []

    if start:
        conditions.append("DATE(created_at) >= ?")
        params.append(start)
    if end:
        conditions.append("DATE(created_at) <= ?")
        params.append(end)
    if conditions:
        query += " WHERE " + " AND ".join(conditions)
    query += " ORDER BY created_at DESC"

    c.execute(query, params)
    rows = c.fetchall()
    conn.close()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "Order Number", "Date", "Time (UTC)",
        "Amount", "Discount", "Items",
        "Method", "Status", "Customer Email"
    ])

    for r in rows:
        dt = (r[1] or "")[:19]
        date_part = dt[:10]
        time_part = dt[11:] if len(dt) > 10 else ""
        try:
            items = json.loads(r[4])
            items_summary = "; ".join(
                f"{i.get('name') or i.get('n', 'Item')} x{i.get('quantity') or i.get('q', 1)}"
                for i in items
            )
        except Exception:
            items_summary = r[4] or ""

        writer.writerow([
            r[0], date_part, time_part,
            f"${r[2]:.2f}",
            f"${r[3]:.2f}" if r[3] else "$0.00",
            items_summary,
            r[5], r[6],
            r[7] or ""
        ])

    output.seek(0)
    filename = f"orders_{datetime.utcnow().strftime('%Y%m%d')}.csv"
    return Response(
        output.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}"}
    )


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
        table { width: 100%; border-collapse: collapse; background: white;
                border-radius: 8px; overflow: hidden; }
        th { background: #0b3d2e; color: white; padding: 10px; text-align: left; }
        td { padding: 10px; border-bottom: 1px solid #f0f0f0; }
        .revenue { font-size: 24px; font-weight: bold; color: #0b3d2e; }
        .export-bar { background: white; border: 1px solid #dde1e7; border-radius: 10px;
                      padding: 16px 20px; margin-bottom: 24px; display: flex;
                      align-items: center; gap: 12px; flex-wrap: wrap; }
        .export-bar label { font-size: 13px; font-weight: 600; color: #374151; }
        .export-bar input { padding: 8px 10px; border: 1px solid #dde1e7;
                            border-radius: 6px; font-size: 13px; }
        .export-btn { padding: 9px 18px; background: #0b3d2e; color: white;
                      border: none; border-radius: 8px; cursor: pointer;
                      font-size: 13px; font-weight: 600; text-decoration: none;
                      display: inline-block; }
        .export-btn:hover { background: #145c44; }
        .export-all { padding: 9px 18px; background: white; color: #0b3d2e;
                      border: 2px solid #0b3d2e; border-radius: 8px; cursor: pointer;
                      font-size: 13px; font-weight: 600; text-decoration: none;
                      display: inline-block; }
        .export-all:hover { background: #f0f7f4; }
    </style>
    <script>
    function exportCSV() {
        const start = document.getElementById("exportStart").value;
        const end = document.getElementById("exportEnd").value;
        let url = "/admin/export";
        const params = [];
        if (start) params.push("start=" + start);
        if (end) params.push("end=" + end);
        if (params.length) url += "?" + params.join("&");
        window.location.href = url;
    }
    </script>
    </head><body>
    <h1>POS Dashboard</h1>
    """

    html += f'<p class="revenue">Total Revenue: ${total_revenue:.2f}</p>'

    html += """
    <div class="export-bar">
      <label>Export Orders to CSV</label>
      <label style="font-weight:normal">From</label>
      <input type="date" id="exportStart" />
      <label style="font-weight:normal">To</label>
      <input type="date" id="exportEnd" />
      <button class="export-btn" onclick="exportCSV()">⬇ Export Range</button>
      <a class="export-all" href="/admin/export">Export All</a>
    </div>
    """

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
        email_line = f"<br><b>Email:</b> {r[9]}" if len(r) > 9 and r[9] else ""
        html += f"""
        <div class="order">
            <b>#{r[1]}</b>
            <span class="badge {method_class}">{r[6]}</span>
            <span class="badge {status_class}">{r[7]}</span><br>
            <b>Amount:</b> ${r[3]:.2f}{discount_line}<br>
            <b>Items:</b> {r[5]}<br>
            <b>Date:</b> {r[8]}{email_line}
        </div>
        """

    html += "</body></html>"
    return html


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
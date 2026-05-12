import os
import stripe
import sqlite3
from datetime import datetime
from flask import Flask, request, jsonify, send_from_directory, session
from functools import wraps
from flask_cors import CORS
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)

# Allow your domain
CORS(app, origins=[os.getenv("ALLOWED_ORIGIN", "https://acwebsite.click")])

# Keys
app.secret_key = os.getenv("FLASK_SECRET_KEY")
stripe.api_key = os.getenv("STRIPE_SECRET_KEY")
endpoint_secret = os.getenv("STRIPE_WEBHOOK_SECRET")

# Session cookie config — required for session to survive Stripe redirect
app.config.update(
    SESSION_COOKIE_SECURE=True,
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE='Lax'
)


# -------------------------
# DATABASE
# -------------------------
def init_db():
    conn = sqlite3.connect("payments.db")
    c = conn.cursor()

    # Fixed — one table named orders, used consistently
    c.execute("""
        CREATE TABLE IF NOT EXISTS orders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            stripe_session_id TEXT UNIQUE,
            amount REAL,
            items TEXT,
            status TEXT,
            created_at TEXT
        )
    """)

    conn.commit()
    conn.close()

init_db()

def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get("user"):
            return jsonify({"error": "unauthorized"}), 401
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
        session["user"] = username
        return jsonify({"username": username})

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
# CREATE CHECKOUT SESSION
# -------------------------
@app.route("/pay", methods=["POST"])
@login_required
def pay():
    data = request.json
    items = data.get("items", [])

    if not items:
        return jsonify({"error": "empty cart"}), 400

    line_items = []

    for item in items:
        line_items.append({
            "price_data": {
                "currency": "usd",
                "product_data": {
                    "name": item["name"]
                },
                "unit_amount": int(item["price"] * 100)
            },
            "quantity": 1
        })

    checkout_session = stripe.checkout.Session.create(
        mode="payment",
        line_items=line_items,
        success_url=os.getenv("SUCCESS_URL", "https://acwebsite.click/success"),
        cancel_url=os.getenv("CANCEL_URL", "https://acwebsite.click/cancel")
    )

    return jsonify({"url": checkout_session.url})


# -------------------------
# WEBHOOK
# -------------------------
@app.route("/webhook", methods=["POST"])
def webhook():
    payload = request.data
    sig_header = request.headers.get("Stripe-Signature")

    try:
        event = stripe.Webhook.construct_event(
            payload, sig_header, endpoint_secret
        )
    except Exception:
        return jsonify({"error": "invalid webhook"}), 400

    if event["type"] == "checkout.session.completed":
        session = event["data"]["object"]

        conn = sqlite3.connect("payments.db")
        c = conn.cursor()

        c.execute("""
            INSERT OR IGNORE INTO orders (
                stripe_session_id,
                amount,
                items,
                status,
                created_at
            ) VALUES (?, ?, ?, ?, ?)
        """, (
            session["id"],
            session["amount_total"] / 100,
            str(session.get("metadata", {})),
            "paid",
            datetime.utcnow().isoformat()
        ))

        conn.commit()
        conn.close()

        print("ORDER SAVED:", session["id"])

    return jsonify({"status": "ok"})


# -------------------------
# ADMIN — protected by token
# -------------------------
@app.route("/admin/orders")
@login_required
def admin_orders():

    conn = sqlite3.connect("payments.db")
    c = conn.cursor()
    c.execute("SELECT * FROM orders ORDER BY id DESC")
    rows = c.fetchall()
    conn.close()

    total_revenue = sum(r[2] for r in rows)

    html = "<h1>POS Dashboard</h1>"

    for r in rows:
        html += f"""
        <div style='border:1px solid #ddd;padding:10px;margin:10px'>
            <b>Order:</b> {r[0]}<br>
            <b>Amount:</b> ${r[2]}<br>
            <b>Status:</b> {r[4]}<br>
            <b>Items:</b> {r[3]}<br>
            <b>Date:</b> {r[5]}
        </div>
        """

    html += f"<h2>Total Revenue: ${total_revenue:.2f}</h2>"
    return html


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
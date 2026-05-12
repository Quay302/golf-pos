import os
import stripe
import sqlite3
from datetime import datetime, timedelta
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

# Session cookie config
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
        session.permanent = True
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

    if not items:
        return jsonify({"error": "empty cart"}), 400

    amount = sum(int(item["price"] * 100) for item in items)

    intent = stripe.PaymentIntent.create(
        amount=amount,
        currency="usd",
        payment_method_types=["card_present"],
        capture_method="automatic",
    )

    return jsonify({"client_secret": intent.client_secret})


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

    if event["type"] == "payment_intent.succeeded":
        payment_intent = event["data"]["object"]

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
            payment_intent["id"],
            payment_intent["amount"] / 100,
            "terminal",
            "paid",
            datetime.utcnow().isoformat()
        ))

        conn.commit()
        conn.close()

        print("ORDER SAVED:", payment_intent["id"])

    return jsonify({"status": "ok"})


# -------------------------
# ADMIN
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
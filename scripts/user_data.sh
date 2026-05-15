#!/bin/bash
set -e
set -o pipefail
exec > /var/log/user_data.log 2>&1

echo "Starting setup..."

# ── System update & packages ──────────────────────────────────────────────────
dnf update -y
dnf install -y python3 python3-pip git nginx certbot python3-certbot-nginx nano

# ── Clone repo ────────────────────────────────────────────────────────────────
git clone https://github.com/Quay302/golf-pos.git /home/ec2-user/golf-pos
chown -R ec2-user:ec2-user /home/ec2-user/golf-pos

# ── Python dependencies ───────────────────────────────────────────────────────
pip3 install -r /home/ec2-user/golf-pos/app/requirements.txt

# ── Environment variables ─────────────────────────────────────────────────────
cat > /home/ec2-user/golf-pos/app/.env << 'EOF'
STRIPE_SECRET_KEY=REPLACE_WITH_YOUR_STRIPE_SECRET_KEY
STRIPE_WEBHOOK_SECRET=REPLACE_WITH_YOUR_STRIPE_WEBHOOK_SECRET
FLASK_SECRET_KEY=REPLACE_WITH_A_RANDOM_SECRET_KEY
ALLOWED_ORIGIN=https://acwebsite.click
SUCCESS_URL=https://acwebsite.click/?success=true
CANCEL_URL=https://acwebsite.click/?cancelled=true
STAFF_USER_1=REPLACE_WITH_STAFF_USERNAME
STAFF_PASS_1=REPLACE_WITH_A_SECURE_PASSWORD
STAFF_USER_2=REPLACE_WITH_STAFF_USERNAME
STAFF_PASS_2=REPLACE_WITH_A_SECURE_PASSWORD
MANAGER_USER=REPLACE_WITH_MANAGER_USERNAME
MANAGER_PASS=REPLACE_WITH_A_SECURE_PASSWORD
EOF

chown ec2-user:ec2-user /home/ec2-user/golf-pos/app/.env
chmod 600 /home/ec2-user/golf-pos/app/.env

# ── Systemd service ───────────────────────────────────────────────────────────
cat > /etc/systemd/system/flaskapp.service << 'EOF'
[Unit]
Description=Golf POS Flask App
After=network.target

[Service]
User=ec2-user
WorkingDirectory=/home/ec2-user/golf-pos/app
EnvironmentFile=/home/ec2-user/golf-pos/app/.env
ExecStart=/usr/local/bin/gunicorn --bind 127.0.0.1:5000 --workers 1 --threads 4 app:app
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable flaskapp
systemctl start flaskapp

# ── Nginx reverse proxy ───────────────────────────────────────────────────────
cat > /etc/nginx/conf.d/flaskapp.conf << 'EOF'
server {
    listen 80;
    server_name acwebsite.click www.acwebsite.click;

    location / {
        proxy_pass         http://127.0.0.1:5000;
        proxy_set_header   Host              $host;
        proxy_set_header   X-Real-IP         $remote_addr;
        proxy_set_header   X-Forwarded-For   $proxy_add_x_forwarded_for;
        proxy_set_header   X-Forwarded-Proto $scheme;
    }
}
EOF

systemctl enable nginx
systemctl start nginx

# ── SSL certificate ───────────────────────────────────────────────────────────
certbot --nginx \
  -d acwebsite.click \
  -d www.acwebsite.click \
  --non-interactive \
  --agree-tos \
  -m ashtoncollins99@gmail.com

echo "Setup complete"
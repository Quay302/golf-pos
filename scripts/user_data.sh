#!/bin/bash
set -e
set -o pipefail
exec > /var/log/user_data.log 2>&1

echo "Starting setup..."
yum update -y
yum install -y python3 git
amazon-linux-extras install nginx1 -y
amazon-linux-extras install epel -y
yum install -y certbot
pip3 install certbot-nginx

# Clone repo
git clone https://github.com/Quay302/golf-pos.git /home/ec2-user/golf-pos

# Install dependencies
pip3 install -r /home/ec2-user/golf-pos/app/requirements.txt
pip3 install gunicorn

# Write env vars
cat > /home/ec2-user/golf-pos/app/.env << EOF
STRIPE_SECRET_KEY=REPLACE_WITH_YOUR_STRIPE_SECRET_KEY
STRIPE_WEBHOOK_SECRET=REPLACE_WITH_YOUR_STRIPE_WEBHOOK_SECRET
STRIPE_PUBLISHABLE_KEY=REPLACE_WITH_YOUR_STRIPE_PUBLISHABLE_KEY
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

# Set up systemd service for Flask
cat > /etc/systemd/system/flaskapp.service << EOF
[Unit]
Description=Golf POS Flask App
After=network.target

[Service]
WorkingDirectory=/home/ec2-user/golf-pos/app
ExecStart=/usr/local/bin/gunicorn --bind 127.0.0.1:5000 app:app
Restart=always

[Install]
WantedBy=multi-user.target
EOF

systemctl enable flaskapp
systemctl start flaskapp

# Set up Nginx as reverse proxy
cat > /etc/nginx/conf.d/flaskapp.conf << EOF
server {
    listen 80;
    server_name acwebsite.click www.acwebsite.click;

    location / {
        proxy_pass http://127.0.0.1:5000;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
    }
}
EOF

systemctl enable nginx
systemctl start nginx

# Get SSL certificate
certbot --nginx -d acwebsite.click -d www.acwebsite.click \
  --non-interactive --agree-tos -m ashtoncollins99@gmail.com

echo "Setup complete"
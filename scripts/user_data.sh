#!/bin/bash
set -e
set -o pipefail
exec > /var/log/user_data.log 2>&1

echo "Starting setup..."
yum update -y
yum install -y python3 git

# Clone repo first
git clone https://github.com/Quay302/golf-pos.git /home/ec2-user/golf-pos

# Then install dependencies
pip3 install -r /home/ec2-user/golf-pos/app/requirements.txt
pip3 install gunicorn

# Write env vars
cat > /home/ec2-user/golf-pos/app/.env << EOF
STRIPE_SECRET_KEY=sk_live_xxx
STRIPE_WEBHOOK_SECRET=whsec_xxx
FLASK_SECRET_KEY=changethistosomethinglong
ALLOWED_ORIGIN=https://yourdomain.com
SUCCESS_URL=https://yourdomain.com/?success=true
CANCEL_URL=https://yourdomain.com/?cancelled=true
STAFF_USER_1=staff1
STAFF_PASS_1=yourpassword
STAFF_USER_2=staff2
STAFF_PASS_2=yourpassword
MANAGER_USER=manager
MANAGER_PASS=yourpassword
EOF

# Set up systemd service
cat > /etc/systemd/system/flaskapp.service << EOF
[Unit]
Description=Golf POS Flask App

[Service]
WorkingDirectory=/home/ec2-user/golf-pos/app
ExecStart=/usr/local/bin/gunicorn --bind 0.0.0.0:5000 app:app
Restart=always

[Install]
WantedBy=multi-user.target
EOF

systemctl enable flaskapp
systemctl start flaskapp
echo "Setup complete"
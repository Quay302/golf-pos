provider "aws" {
  region = var.aws_region
}

# ── Latest Amazon Linux 2023 AMI (auto-resolves, never goes stale) ────────────
data "aws_ami" "al2023" {
  most_recent = true
  owners      = ["amazon"]

  filter {
    name   = "name"
    values = ["al2023-ami-*-x86_64"]
  }

  filter {
    name   = "architecture"
    values = ["x86_64"]
  }

  filter {
    name   = "virtualization-type"
    values = ["hvm"]
  }
}

resource "aws_security_group" "flask_sg" {
  name = "flask-sg"

  # SSH — open to all IPs; GitHub Actions needs this (IPs change constantly).
  # Security comes from the private key stored in GitHub Secrets, not IP restriction.
  ingress {
    from_port   = 22
    to_port     = 22
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  # HTTP
  ingress {
    from_port   = 80
    to_port     = 80
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  # HTTPS
  ingress {
    from_port   = 443
    to_port     = 443
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
}

resource "aws_instance" "flask_server" {
  ami                    = data.aws_ami.al2023.id
  instance_type          = var.instance_type
  key_name               = var.key_name
  vpc_security_group_ids = [aws_security_group.flask_sg.id]

  # main.tf is inside terraform/, scripts is one level up
  user_data = file("${path.module}/../scripts/user_data.sh")

  root_block_device {
    volume_size           = 20
    volume_type           = "gp3"
    delete_on_termination = true
  }

  tags = {
    Name = "GolfPOS"
  }
}

# Elastic IP — keeps same IP across destroy/apply
resource "aws_eip" "flask_eip" {
  instance = aws_instance.flask_server.id
  domain   = "vpc"
}

# Route53 — point domain to Elastic IP
data "aws_route53_zone" "main" {
  name = var.domain_name
}

resource "aws_route53_record" "flask_a" {
  zone_id         = data.aws_route53_zone.main.zone_id
  name            = var.domain_name
  type            = "A"
  ttl             = 300
  records         = [aws_eip.flask_eip.public_ip]
  allow_overwrite = true
}

# www redirect
resource "aws_route53_record" "flask_www" {
  zone_id         = data.aws_route53_zone.main.zone_id
  name            = "www.${var.domain_name}"
  type            = "A"
  ttl             = 300
  records         = [aws_eip.flask_eip.public_ip]
  allow_overwrite = true
}

# ── SendGrid Domain Authentication ───────────────────────────────────────────
resource "aws_route53_record" "sendgrid_url" {
  zone_id = data.aws_route53_zone.main.zone_id
  name    = "url7675.acwebsite.click"
  type    = "CNAME"
  ttl     = 300
  records = ["sendgrid.net"]
}

resource "aws_route53_record" "sendgrid_domainkey" {
  zone_id = data.aws_route53_zone.main.zone_id
  name    = "107521873.acwebsite.click"
  type    = "CNAME"
  ttl     = 300
  records = ["sendgrid.net"]
}

resource "aws_route53_record" "sendgrid_em" {
  zone_id = data.aws_route53_zone.main.zone_id
  name    = "em7267.acwebsite.click"
  type    = "CNAME"
  ttl     = 300
  records = ["u107521873.wl124.sendgrid.net"]
}

resource "aws_route53_record" "sendgrid_s1" {
  zone_id = data.aws_route53_zone.main.zone_id
  name    = "s1._domainkey.acwebsite.click"
  type    = "CNAME"
  ttl     = 300
  records = ["s1.domainkey.u107521873.wl124.sendgrid.net"]
}

resource "aws_route53_record" "sendgrid_s2" {
  zone_id = data.aws_route53_zone.main.zone_id
  name    = "s2._domainkey.acwebsite.click"
  type    = "CNAME"
  ttl     = 300
  records = ["s2.domainkey.u107521873.wl124.sendgrid.net"]
}

resource "aws_route53_record" "sendgrid_dmarc" {
  zone_id = data.aws_route53_zone.main.zone_id
  name    = "_dmarc.acwebsite.click"
  type    = "TXT"
  ttl     = 300
  records = ["v=DMARC1; p=none;"]
}
provider "aws" {
  region = var.aws_region
}

resource "aws_security_group" "flask_sg" {
  name = "flask-sg"

  # SSH — open for GitHub Actions deploys
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
  ami                    = var.ami_id
  instance_type          = var.instance_type
  key_name               = var.key_name
  vpc_security_group_ids = [aws_security_group.flask_sg.id]

  # Fixed path — main.tf is inside terraform/, scripts is one level up
  user_data = file("${path.module}/../scripts/user_data.sh")

  tags = {
    Name = "GolfPOS"
  }
}

# Elastic IP — keeps same IP across destroy/apply
resource "aws_eip" "flask_eip" {
  instance = aws_instance.flask_server.id
  domain   = "vpc"
}

# Route53 - point your domain to the Elastic IP
data "aws_route53_zone" "main" {
  name = "acwebsite.click"
}

resource "aws_route53_record" "flask_a" {
  zone_id = data.aws_route53_zone.main.zone_id
  name    = "acwebsite.click"
  type    = "A"
  ttl     = 300
  records = [aws_eip.flask_eip.public_ip]
  allow_overwrite = true
}

# www redirect
resource "aws_route53_record" "flask_www" {
  zone_id = data.aws_route53_zone.main.zone_id
  name    = "www.acwebsite.click"
  type    = "A"
  ttl     = 300
  records = [aws_eip.flask_eip.public_ip]
}

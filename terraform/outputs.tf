output "elastic_ip" {
  description = "Fixed public IP — use this in GitHub secrets as EC2_HOST"
  value       = aws_eip.flask_eip.public_ip
}

output "instance_id" {
  description = "EC2 instance ID"
  value       = aws_instance.flask_server.id
}

output "ami_used" {
  description = "AL2023 AMI ID resolved at apply time"
  value       = data.aws_ami.al2023.id
}

variable "aws_region" {
  description = "AWS region"
  type        = string
  default     = "us-east-1"
}

variable "ami_id" {
  description = "EC2 AMI ID"
  type        = string
}

variable "instance_type" {
  description = "EC2 instance type"
  type        = string
  default     = "t2.micro"
}

variable "key_name" {
  description = "Name of your AWS key pair"
  type        = string
}

variable "my_ip" {
  description = "Your IP for SSH access — format: x.x.x.x/32"
  type        = string
}

variable "domain_name" {
  description = "Your domain name"
  type        = string
}
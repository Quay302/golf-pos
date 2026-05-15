variable "aws_region" {
  description = "AWS region"
  type        = string
  default     = "us-east-1"
}

variable "instance_type" {
  description = "EC2 instance type"
  type        = string
  default     = "t3.small"
}

variable "key_name" {
  description = "Name of your AWS key pair"
  type        = string
}

variable "domain_name" {
  description = "Your domain name"
  type        = string
}

terraform {
  required_version = ">= 1.3.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.0"
    }
  }

  backend "s3" {
    bucket = "golf-pos-terraform-state"
    key    = "golf-pos/terraform.tfstate"
    region = "us-east-1"
  }
}

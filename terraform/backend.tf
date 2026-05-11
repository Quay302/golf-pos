terraform {
  backend "s3" {
    bucket = "golf-pos-terraform-state"
    key    = "golf-pos/terraform.tfstate"
    region = "us-east-1"
  }
}
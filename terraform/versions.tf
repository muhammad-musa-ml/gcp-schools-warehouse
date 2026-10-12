terraform {
  required_version = ">= 1.9"

  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 8.6"
    }
    time = {
      source  = "hashicorp/time"
      version = "~> 0.14"
    }
  }
}

provider "google" {
  project = var.project_id
  region  = var.region

  # Act on behalf of the project itself, so API quota and the enable-API checks
  # are charged to it and not to whatever project the local credentials default to.
  user_project_override = true
  billing_project       = var.project_id
}

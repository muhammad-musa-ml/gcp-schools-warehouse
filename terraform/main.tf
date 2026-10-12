locals {
  bucket_name = coalesce(var.bucket_name, "${var.project_id}-schools-raw")

  apis = toset([
    "serviceusage.googleapis.com",
    "cloudresourcemanager.googleapis.com",
    "storage.googleapis.com",
    "bigquery.googleapis.com",
    "bigqueryconnection.googleapis.com",
    "aiplatform.googleapis.com",
  ])
}

resource "google_project_service" "api" {
  for_each = local.apis

  service = each.value

  # Leave the APIs on at destroy: other things in the project may be using them.
  disable_on_destroy = false
}

resource "google_storage_bucket" "raw" {
  name     = local.bucket_name
  location = var.location
  labels   = var.labels

  uniform_bucket_level_access = true
  public_access_prevention    = "enforced"
  force_destroy               = var.force_destroy

  depends_on = [google_project_service.api]
}

resource "google_bigquery_dataset" "raw" {
  dataset_id = var.raw_dataset
  location   = var.location
  labels     = var.labels

  # Every table in here is rebuilt by the pipeline.
  delete_contents_on_destroy = true

  depends_on = [google_project_service.api]
}

resource "google_bigquery_dataset" "warehouse" {
  dataset_id = var.warehouse_dataset
  location   = var.location
  labels     = var.labels

  delete_contents_on_destroy = true

  depends_on = [google_project_service.api]
}

resource "google_bigquery_dataset" "assertions" {
  dataset_id = var.assertions_dataset
  location   = var.location
  labels     = var.labels

  delete_contents_on_destroy = true

  depends_on = [google_project_service.api]
}

# AI.CLASSIFY calls Vertex AI through this connection's service account.
resource "google_bigquery_connection" "ai" {
  connection_id = var.ai_connection_id
  location      = var.location
  friendly_name = "Vertex AI for AI.CLASSIFY"

  cloud_resource {}

  depends_on = [google_project_service.api]
}

resource "google_project_iam_member" "ai_connection_vertex_user" {
  project = var.project_id
  role    = "roles/aiplatform.user"
  member  = "serviceAccount:${google_bigquery_connection.ai.cloud_resource[0].service_account_id}"
}

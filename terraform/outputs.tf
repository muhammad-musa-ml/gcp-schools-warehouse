output "project_id" {
  value = var.project_id
}

output "location" {
  value = var.location
}

output "bucket" {
  value = google_storage_bucket.raw.name
}

output "raw_dataset" {
  value = google_bigquery_dataset.raw.dataset_id
}

output "warehouse_dataset" {
  value = google_bigquery_dataset.warehouse.dataset_id
}

# project.location.id, the form AI.CLASSIFY wants in connection_id
output "ai_connection" {
  value = "${var.project_id}.${var.location}.${google_bigquery_connection.ai.connection_id}"
}

output "ai_connection_service_account" {
  value = google_bigquery_connection.ai.cloud_resource[0].service_account_id
}

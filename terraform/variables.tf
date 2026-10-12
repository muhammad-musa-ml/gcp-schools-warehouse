variable "project_id" {
  description = "GCP project that holds the bucket, datasets and connection."
  type        = string
}

variable "location" {
  description = "Location for the bucket, datasets and connection. Keep US: the public boundary tables live there."
  type        = string
  default     = "US"
}

variable "region" {
  description = "Default region for the provider; nothing in this stack is regional."
  type        = string
  default     = "us-central1"
}

variable "bucket_name" {
  description = "Raw-files bucket. Null derives <project_id>-schools-raw."
  type        = string
  default     = null
}

variable "raw_dataset" {
  description = "BigQuery dataset the Parquet is loaded into."
  type        = string
  default     = "schools_raw"
}

variable "warehouse_dataset" {
  description = "BigQuery dataset for the modelled tables."
  type        = string
  default     = "schools_warehouse"
}

variable "assertions_dataset" {
  description = "BigQuery dataset where Dataform keeps its assertion views."
  type        = string
  default     = "schools_assertions"
}

variable "ai_connection_id" {
  description = "Id of the BigQuery connection that AI.CLASSIFY calls Vertex AI through."
  type        = string
  default     = "schools-ai"
}

variable "force_destroy" {
  description = "Let terraform destroy delete a bucket that still holds objects. The CLI empties the bucket itself, so this stays off."
  type        = bool
  default     = false
}

variable "labels" {
  description = "Labels put on the bucket and datasets."
  type        = map(string)
  default = {
    app = "schools-warehouse"
  }
}

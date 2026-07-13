# ------------------------------------------------------------------------------
# Subscription / existing-infrastructure names (discovered live 2026-07)
# ------------------------------------------------------------------------------

variable "subscription_id" {
  description = "Azure subscription hosting rg-mcp-prod-001 (no default: pass explicitly or via ARM_SUBSCRIPTION_ID)."
  type        = string
}

variable "resource_group_name" {
  description = "Resource group of the Container Apps environment, ACR, and this stack's resources."
  type        = string
  default     = "rg-mcp-prod-001"
}

variable "container_app_environment_name" {
  description = "Existing workload-profiles Container Apps environment (custom VNet, Central US). Referenced, never managed."
  type        = string
  default     = "cae-mcp-prod-002"
}

variable "acr_name" {
  description = "Existing container registry holding the doc-intel-analysts image."
  type        = string
  default     = "formenteramcp"
}

variable "key_vault_name" {
  description = "Shared enterprise key vault holding the doc-intel secrets."
  type        = string
  default     = "kv-enterprise-shared-001"
}

variable "key_vault_resource_group_name" {
  description = "Resource group of the shared key vault."
  type        = string
  default     = "rg-enterprise-shared-001"
}

# ------------------------------------------------------------------------------
# Image + rollout gating
# ------------------------------------------------------------------------------

variable "image_tag" {
  description = "Tag of formenteramcp.azurecr.io/doc-intel-analysts to deploy. No default: pin every apply."
  type        = string
}

variable "deploy_service" {
  description = "Wave 2 gate: false deploys storage + the gate job only; true adds the service and the ingest/maintenance/graph-rebuild jobs (flip only after the NFS bootstrap parity gate passes)."
  type        = bool
  default     = false
}

# ------------------------------------------------------------------------------
# Networking (shared production subnet/NSG — identified, never managed)
# ------------------------------------------------------------------------------

variable "infrastructure_subnet_id" {
  description = "Resource ID of the environment's infrastructure subnet; becomes the storage account's only allowed network (needs the Microsoft.Storage service endpoint)."
  type        = string
}

variable "nsg_name" {
  description = "Name of the NSG attached to the environment's infrastructure subnet. Only NEW allow rules are added; existing rules are never modified."
  type        = string
}

variable "nsg_resource_group_name" {
  description = "Resource group of the subnet's NSG."
  type        = string
  default     = "rg-mcp-prod-001"
}

variable "nsg_rule_priority_smb" {
  description = "Priority for the outbound 445 allow rule (must not collide with existing rules)."
  type        = number
  default     = 3900
}

variable "nsg_rule_priority_nfs" {
  description = "Priority for the outbound 2049 allow rule (must not collide with existing rules)."
  type        = number
  default     = 3901
}

# ------------------------------------------------------------------------------
# Storage
# ------------------------------------------------------------------------------

variable "storage_account_name" {
  description = "Globally-unique name for the Premium FileStorage account backing the NFS share."
  type        = string
  default     = "stdocintelanalysts"
}

variable "share_name" {
  description = "NFS file share carrying the evidence/cognee/masters sub_paths."
  type        = string
  default     = "doc-intel-store"
}

variable "share_quota_gib" {
  description = "Provisioned share size in GiB (premium bills on provisioned size)."
  type        = number
  default     = 200
}

# ------------------------------------------------------------------------------
# Runtime
# ------------------------------------------------------------------------------

variable "aws_region" {
  description = "Region for the S3 derived/raw buckets (boto3 AWS_DEFAULT_REGION on containers holding AWS credentials)."
  type        = string
  default     = "us-east-1"
}

variable "maintenance_workload_profile_name" {
  description = "Dedicated workload profile the maintenance job runs on. Added via CLI, not this stack — see README."
  type        = string
  default     = "E8"
}

# ------------------------------------------------------------------------------
# Key Vault secret NAMES (values live only in the vault, never here)
# ------------------------------------------------------------------------------

variable "gateway_key_secret_name" {
  description = "KV secret name for the Vercel AI Gateway API key."
  type        = string
  default     = "doc-intel-gateway-key"
}

variable "analysts_token_secret_name" {
  description = "KV secret name for the analysts service bearer token."
  type        = string
  default     = "doc-intel-analysts-token"
}

variable "aws_access_key_id_secret_name" {
  description = "KV secret name for the S3 reader access key id."
  type        = string
  default     = "doc-intel-aws-access-key-id"
}

variable "aws_secret_access_key_secret_name" {
  description = "KV secret name for the S3 reader secret access key."
  type        = string
  default     = "doc-intel-aws-secret-access-key"
}

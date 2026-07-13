output "service_url" {
  description = "External ingress URL of the analysts service (null until deploy_service = true)."
  value       = var.deploy_service ? "https://${one(azurerm_container_app.analysts).ingress[0].fqdn}" : null
}

output "storage_account_name" {
  description = "Premium FileStorage account backing the NFS share."
  value       = azurerm_storage_account.doc_intel.name
}

output "share_name" {
  description = "NFS share carrying the evidence/cognee/masters sub_paths."
  value       = azurerm_storage_share.doc_intel.name
}

output "identity_principal_id" {
  description = "Principal id of the shared user-assigned identity (for the R10 RBAC enumeration)."
  value       = azurerm_user_assigned_identity.analysts.principal_id
}

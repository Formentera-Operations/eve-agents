################################################################################
# Premium NFS file share backing the three doc-intel stores
# (.evidence / .cognee / .masters as sub_paths of one 200 GiB share).
#
# NFS requires "secure transfer required" OFF and a VNet-scoped network rule
# set; the Container Apps environment's infrastructure subnet is the only
# allowed network (it needs the Microsoft.Storage service endpoint — README).
################################################################################

resource "azurerm_storage_account" "doc_intel" {
  name                     = var.storage_account_name
  resource_group_name      = var.resource_group_name
  location                 = local.location
  account_kind             = "FileStorage"
  account_tier             = "Premium"
  account_replication_type = "LRS"

  # NFS 4.1 does not support encryption in transit via the HTTPS/SMB path;
  # the share is protected by the VNet scoping below instead.
  https_traffic_only_enabled = false

  network_rules {
    default_action             = "Deny"
    bypass                     = ["AzureServices"]
    virtual_network_subnet_ids = [var.infrastructure_subnet_id]
  }

  tags = local.tags
}

resource "azurerm_storage_share" "doc_intel" {
  name               = var.share_name
  storage_account_id = azurerm_storage_account.doc_intel.id
  quota              = var.share_quota_gib
  enabled_protocol   = "NFS"
}

# Registers the NFS share with the (unmanaged, data-sourced) environment so
# apps and jobs can mount it by storage_name.
resource "azurerm_container_app_environment_storage" "doc_intel" {
  name                         = local.volume_name
  container_app_environment_id = data.azurerm_container_app_environment.mcp.id
  access_mode                  = "ReadWrite"
  nfs_server_url               = "${azurerm_storage_account.doc_intel.name}.file.core.windows.net"
  share_name                   = "/${azurerm_storage_account.doc_intel.name}/${azurerm_storage_share.doc_intel.name}"
}

# ------------------------------------------------------------------------------
# NSG allow rules for Azure Files (SMB 445 / NFS 2049) on the environment's
# infrastructure subnet. The NSG is SHARED PRODUCTION infrastructure: this
# stack only ADDS the two allow rules below and never touches existing rules.
# Priorities are variables so they can be slotted around what already exists.
# ------------------------------------------------------------------------------

resource "azurerm_network_security_rule" "storage_smb_445" {
  name                        = "allow-doc-intel-storage-smb-445"
  resource_group_name         = var.nsg_resource_group_name
  network_security_group_name = var.nsg_name
  priority                    = var.nsg_rule_priority_smb
  direction                   = "Outbound"
  access                      = "Allow"
  protocol                    = "Tcp"
  source_port_range           = "*"
  destination_port_range      = "445"
  source_address_prefix       = "VirtualNetwork"
  destination_address_prefix  = "Storage"
}

resource "azurerm_network_security_rule" "storage_nfs_2049" {
  name                        = "allow-doc-intel-storage-nfs-2049"
  resource_group_name         = var.nsg_resource_group_name
  network_security_group_name = var.nsg_name
  priority                    = var.nsg_rule_priority_nfs
  direction                   = "Outbound"
  access                      = "Allow"
  protocol                    = "Tcp"
  source_port_range           = "*"
  destination_port_range      = "2049"
  source_address_prefix       = "VirtualNetwork"
  destination_address_prefix  = "Storage"
}

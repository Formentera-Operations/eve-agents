################################################################################
# doc-intel analysts — Azure Container Apps stack (plan U4)
#
# Hosts the FastAPI analysts service plus four batch jobs (gate, ingest,
# maintenance, graph-rebuild) against the EXISTING cae-mcp-prod-002
# environment. The environment, registry, and key vault are referenced via
# data sources — this stack never manages them.
#
# State is secret-bearing (the storage account key lands in state): it MUST
# live in the RBAC'd remote Azure blob backend below — never local, never
# committed. See README.md.
################################################################################

terraform {
  required_version = ">= 1.5"

  required_providers {
    azurerm = { source = "hashicorp/azurerm", version = "~> 4.0" }
  }

  # PLACEHOLDERS — fill with the real RBAC'd state backend before `init`.
  # The gis-snowflake-extractor sibling uses local state; this stack must not
  # (its state carries the Files storage account key).
  backend "azurerm" {
    resource_group_name  = "REPLACE_ME-state-rg"
    storage_account_name = "replacemestatesa"
    container_name       = "tfstate"
    key                  = "doc-intel-analysts.tfstate"
    use_azuread_auth     = true # RBAC, not account keys
  }
}

provider "azurerm" {
  features {}
  subscription_id = var.subscription_id
}

# ------------------------------------------------------------------------------
# Existing infrastructure — referenced, never managed here
# ------------------------------------------------------------------------------

data "azurerm_container_app_environment" "mcp" {
  name                = var.container_app_environment_name
  resource_group_name = var.resource_group_name
}

data "azurerm_container_registry" "mcp" {
  name                = var.acr_name
  resource_group_name = var.resource_group_name
}

data "azurerm_key_vault" "shared" {
  name                = var.key_vault_name
  resource_group_name = var.key_vault_resource_group_name
}

# ------------------------------------------------------------------------------
# Shared locals
# ------------------------------------------------------------------------------

locals {
  app_name = "doc-intel-analysts"
  location = data.azurerm_container_app_environment.mcp.location
  app_root = "/app/agents/doc-intel/analysts" # Dockerfile WORKDIR
  image    = "${data.azurerm_container_registry.mcp.login_server}/doc-intel-analysts:${var.image_tag}"

  # Silent-egress guard set (graph/config.py `configure()` + `_assert_gateway_only()`).
  # configure() setdefaults these, but Terraform pins them so a code regression
  # cannot silently re-route content off the gateway path. Non-secret only —
  # LLM_API_KEY / EMBEDDING_API_KEY are derived at runtime from AI_GATEWAY_API_KEY.
  guard_env = [
    { name = "LLM_ENDPOINT", value = "https://ai-gateway.vercel.sh/v1" },
    { name = "EMBEDDING_ENDPOINT", value = "https://ai-gateway.vercel.sh/v1" },
    { name = "TELEMETRY_DISABLED", value = "1" },
    { name = "CACHING", value = "false" },
    { name = "LLM_INSTRUCTOR_MODE", value = "tool_call" },
    { name = "EMBEDDING_MODEL", value = "text-embedding-3-large" },
    { name = "EMBEDDING_DIMENSIONS", value = "3072" },
    { name = "EMBEDDING_MAX_TOKENS", value = "8191" },
  ]

  # One NFS share, three sub_path mounts (KTD3 store layout).
  volume_name = "doc-intel-store"
  mounts = [
    { sub_path = "evidence", path = "${local.app_root}/.evidence" },
    { sub_path = "cognee", path = "${local.app_root}/.cognee" },
    { sub_path = "masters", path = "${local.app_root}/.masters" },
  ]

  tags = {
    initiative = "doc-intel"
    component  = "analysts"
    stack      = "container-apps"
  }
}

# ------------------------------------------------------------------------------
# Identity + IAM — one user-assigned identity shared by the service and jobs
# ------------------------------------------------------------------------------

resource "azurerm_user_assigned_identity" "analysts" {
  name                = "${local.app_name}-identity"
  resource_group_name = var.resource_group_name
  location            = local.location
  tags                = local.tags
}

resource "azurerm_role_assignment" "analysts_kv_secrets" {
  scope                = data.azurerm_key_vault.shared.id
  role_definition_name = "Key Vault Secrets User"
  principal_id         = azurerm_user_assigned_identity.analysts.principal_id
}

resource "azurerm_role_assignment" "analysts_acr_pull" {
  scope                = data.azurerm_container_registry.mcp.id
  role_definition_name = "AcrPull"
  principal_id         = azurerm_user_assigned_identity.analysts.principal_id
}

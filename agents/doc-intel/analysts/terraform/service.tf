################################################################################
# The analysts FastAPI service (uvicorn on 8734) — wave 2 only.
#
# Gated behind var.deploy_service: wave 1 stands up storage + the gate job,
# and the service deploys only after the NFS bootstrap parity gate passes.
# Exactly one replica: the embedded Kuzu/LanceDB stores are single-writer.
################################################################################

resource "azurerm_container_app" "analysts" {
  count = var.deploy_service ? 1 : 0

  name                         = local.app_name
  resource_group_name          = var.resource_group_name
  container_app_environment_id = data.azurerm_container_app_environment.mcp.id
  revision_mode                = "Single"
  workload_profile_name        = "Consumption"

  identity {
    type         = "UserAssigned"
    identity_ids = [azurerm_user_assigned_identity.analysts.id]
  }

  registry {
    server   = data.azurerm_container_registry.mcp.login_server
    identity = azurerm_user_assigned_identity.analysts.id
  }

  ingress {
    external_enabled           = true
    target_port                = 8734
    allow_insecure_connections = false

    traffic_weight {
      latest_revision = true
      percentage      = 100
    }
  }

  template {
    min_replicas = 1
    max_replicas = 1

    volume {
      name         = local.volume_name
      storage_type = "NfsAzureFile"
      storage_name = azurerm_container_app_environment_storage.doc_intel.name
    }

    container {
      name   = local.app_name
      image  = local.image
      cpu    = 2
      memory = "4Gi"

      # Silent-egress guard — pinned on every container (see main.tf locals).
      dynamic "env" {
        for_each = local.guard_env
        content {
          name  = env.value.name
          value = env.value.value
        }
      }

      # Hosted mode fails closed: service refuses to start without the token.
      env {
        name  = "ANALYSTS_REQUIRE_AUTH"
        value = "1"
      }
      env {
        name  = "AWS_DEFAULT_REGION"
        value = var.aws_region
      }

      env {
        name        = "AI_GATEWAY_API_KEY"
        secret_name = "ai-gateway-api-key"
      }
      env {
        name        = "ANALYSTS_API_TOKEN"
        secret_name = "analysts-api-token"
      }
      env {
        name        = "AWS_ACCESS_KEY_ID"
        secret_name = "aws-access-key-id"
      }
      env {
        name        = "AWS_SECRET_ACCESS_KEY"
        secret_name = "aws-secret-access-key"
      }

      dynamic "volume_mounts" {
        for_each = local.mounts
        content {
          name     = local.volume_name
          path     = volume_mounts.value.path
          sub_path = volume_mounts.value.sub_path
        }
      }
    }
  }

  # Key Vault references resolved via the managed identity — no literal values.
  secret {
    name                = "ai-gateway-api-key"
    identity            = azurerm_user_assigned_identity.analysts.id
    key_vault_secret_id = "${data.azurerm_key_vault.shared.vault_uri}secrets/${var.gateway_key_secret_name}"
  }
  secret {
    name                = "analysts-api-token"
    identity            = azurerm_user_assigned_identity.analysts.id
    key_vault_secret_id = "${data.azurerm_key_vault.shared.vault_uri}secrets/${var.analysts_token_secret_name}"
  }
  secret {
    name                = "aws-access-key-id"
    identity            = azurerm_user_assigned_identity.analysts.id
    key_vault_secret_id = "${data.azurerm_key_vault.shared.vault_uri}secrets/${var.aws_access_key_id_secret_name}"
  }
  secret {
    name                = "aws-secret-access-key"
    identity            = azurerm_user_assigned_identity.analysts.id
    key_vault_secret_id = "${data.azurerm_key_vault.shared.vault_uri}secrets/${var.aws_secret_access_key_secret_name}"
  }

  tags = local.tags
}

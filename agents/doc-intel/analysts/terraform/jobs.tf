################################################################################
# Batch jobs. All four mount the same NFS share via the three sub_path
# mounts. The image has no ENTRYPOINT, so `args` IS the container command
# (Dockerfile convention: plain CMD, jobs override the whole command).
#
#   gate          wave 1 — replica bootstrap down-sync + parity check (NFS gate)
#   ingest        wave 2 — evidence batch ingest (cron authored, disabled)
#   maintenance   wave 2 — index build + compaction on the E8 dedicated profile
#   graph-rebuild wave 2 — cognee graph ingest (service MUST be stopped: Kuzu
#                          is single-writer, an idle service still holds the lock)
################################################################################

# --- gate (wave 1: NOT gated by deploy_service) -------------------------------

resource "azurerm_container_app_job" "gate" {
  name                         = "${local.app_name}-gate"
  resource_group_name          = var.resource_group_name
  location                     = local.location
  container_app_environment_id = data.azurerm_container_app_environment.mcp.id
  workload_profile_name        = "Consumption"

  replica_timeout_in_seconds = 14400 # full-store S3 down-sync is hours, not minutes
  replica_retry_limit        = 0     # idempotent resume — restart manually after triage

  manual_trigger_config {
    parallelism              = 1
    replica_completion_count = 1
  }

  identity {
    type         = "UserAssigned"
    identity_ids = [azurerm_user_assigned_identity.analysts.id]
  }

  registry {
    server   = data.azurerm_container_registry.mcp.login_server
    identity = azurerm_user_assigned_identity.analysts.id
  }

  template {
    volume {
      name         = local.volume_name
      storage_type = "NfsAzureFile"
      storage_name = azurerm_container_app_environment_storage.doc_intel.name
    }

    container {
      name   = "gate"
      image  = local.image
      cpu    = 2
      memory = "4Gi"
      args   = ["python", "-m", "doc_intel_analysts.evidence.replica", "--bootstrap"]

      dynamic "env" {
        for_each = local.guard_env
        content {
          name  = env.value.name
          value = env.value.value
        }
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

  secret {
    name                = "ai-gateway-api-key"
    identity            = azurerm_user_assigned_identity.analysts.id
    key_vault_secret_id = "${data.azurerm_key_vault.shared.vault_uri}secrets/${var.gateway_key_secret_name}"
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

# --- ingest (wave 2) -----------------------------------------------------------

resource "azurerm_container_app_job" "ingest" {
  count = var.deploy_service ? 1 : 0

  name                         = "${local.app_name}-ingest"
  resource_group_name          = var.resource_group_name
  location                     = local.location
  container_app_environment_id = data.azurerm_container_app_environment.mcp.id
  workload_profile_name        = "Consumption"

  replica_timeout_in_seconds = 14400
  replica_retry_limit        = 0

  manual_trigger_config {
    parallelism              = 1
    replica_completion_count = 1
  }

  # Cron authored but DISABLED until batch cadence is proven. NOTE: an ACA
  # job's trigger type cannot be changed in place — enabling this means
  # replacing the job (delete manual_trigger_config, uncomment, taint/apply).
  # schedule_trigger_config {
  #   cron_expression          = "0 6 * * *"
  #   parallelism              = 1
  #   replica_completion_count = 1
  # }

  identity {
    type         = "UserAssigned"
    identity_ids = [azurerm_user_assigned_identity.analysts.id]
  }

  registry {
    server   = data.azurerm_container_registry.mcp.login_server
    identity = azurerm_user_assigned_identity.analysts.id
  }

  template {
    volume {
      name         = local.volume_name
      storage_type = "NfsAzureFile"
      storage_name = azurerm_container_app_environment_storage.doc_intel.name
    }

    container {
      name   = "ingest"
      image  = local.image
      cpu    = 2
      memory = "4Gi"
      # A source flag (--manifest / --prefix) is REQUIRED at start time — see
      # README "Running ingest" for the `az containerapp job start --args`
      # override; these template args alone exit with an argparse error.
      args = ["python", "-m", "doc_intel_analysts.evidence.ingest", "--max-new", "250"]

      dynamic "env" {
        for_each = local.guard_env
        content {
          name  = env.value.name
          value = env.value.value
        }
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

  secret {
    name                = "ai-gateway-api-key"
    identity            = azurerm_user_assigned_identity.analysts.id
    key_vault_secret_id = "${data.azurerm_key_vault.shared.vault_uri}secrets/${var.gateway_key_secret_name}"
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

# --- maintenance (wave 2, E8 dedicated profile) ----------------------------------

resource "azurerm_container_app_job" "maintenance" {
  count = var.deploy_service ? 1 : 0

  name                         = "${local.app_name}-maintenance"
  resource_group_name          = var.resource_group_name
  location                     = local.location
  container_app_environment_id = data.azurerm_container_app_environment.mcp.id
  workload_profile_name        = var.maintenance_workload_profile_name

  replica_timeout_in_seconds = 21600 # FTS rebuild + full compaction
  replica_retry_limit        = 0

  manual_trigger_config {
    parallelism              = 1
    replica_completion_count = 1
  }

  identity {
    type         = "UserAssigned"
    identity_ids = [azurerm_user_assigned_identity.analysts.id]
  }

  registry {
    server   = data.azurerm_container_registry.mcp.login_server
    identity = azurerm_user_assigned_identity.analysts.id
  }

  template {
    volume {
      name         = local.volume_name
      storage_type = "NfsAzureFile"
      storage_name = azurerm_container_app_environment_storage.doc_intel.name
    }

    container {
      name   = "maintenance"
      image  = local.image
      cpu    = 4
      memory = "32Gi" # dedicated profile: raise freely within the E8 node
      args   = ["python", "-m", "doc_intel_analysts.evidence.ingest", "--maintain"]

      dynamic "env" {
        for_each = local.guard_env
        content {
          name  = env.value.name
          value = env.value.value
        }
      }
      # No AWS credentials: maintenance touches only the local stores.
      env {
        name        = "AI_GATEWAY_API_KEY"
        secret_name = "ai-gateway-api-key"
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

  secret {
    name                = "ai-gateway-api-key"
    identity            = azurerm_user_assigned_identity.analysts.id
    key_vault_secret_id = "${data.azurerm_key_vault.shared.vault_uri}secrets/${var.gateway_key_secret_name}"
  }

  tags = local.tags
}

# --- graph-rebuild (wave 2) ------------------------------------------------------

resource "azurerm_container_app_job" "graph_rebuild" {
  count = var.deploy_service ? 1 : 0

  name                         = "${local.app_name}-graph-rebuild"
  resource_group_name          = var.resource_group_name
  location                     = local.location
  container_app_environment_id = data.azurerm_container_app_environment.mcp.id
  workload_profile_name        = "Consumption"

  replica_timeout_in_seconds = 21600 # cognify over the full corpus is hours
  replica_retry_limit        = 0

  manual_trigger_config {
    parallelism              = 1
    replica_completion_count = 1
  }

  identity {
    type         = "UserAssigned"
    identity_ids = [azurerm_user_assigned_identity.analysts.id]
  }

  registry {
    server   = data.azurerm_container_registry.mcp.login_server
    identity = azurerm_user_assigned_identity.analysts.id
  }

  template {
    volume {
      name         = local.volume_name
      storage_type = "NfsAzureFile"
      storage_name = azurerm_container_app_environment_storage.doc_intel.name
    }

    container {
      name   = "graph-rebuild"
      image  = local.image
      cpu    = 2
      memory = "4Gi"
      args   = ["python", "-m", "doc_intel_analysts.graph.ingest"]

      dynamic "env" {
        for_each = local.guard_env
        content {
          name  = env.value.name
          value = env.value.value
        }
      }
      env {
        name        = "AI_GATEWAY_API_KEY"
        secret_name = "ai-gateway-api-key"
      }
      # graph/ingest.py reads parsed docs from the derived bucket AND writes
      # its run ledger back to it (_s3.put_object) — the AWS pair is required.
      env {
        name  = "AWS_DEFAULT_REGION"
        value = var.aws_region
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

  secret {
    name                = "ai-gateway-api-key"
    identity            = azurerm_user_assigned_identity.analysts.id
    key_vault_secret_id = "${data.azurerm_key_vault.shared.vault_uri}secrets/${var.gateway_key_secret_name}"
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

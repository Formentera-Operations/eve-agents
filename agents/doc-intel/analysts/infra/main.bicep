////////////////////////////////////////////////////////////////////////////////
// doc-intel analysts — Azure Container Apps stack (plan U4)
//
// Hosts the FastAPI analysts service plus four batch jobs (gate, ingest,
// maintenance, graph-rebuild) against the EXISTING cae-mcp-prod-002
// environment. The environment, registry, NSG, and key vault are referenced
// as `existing` resources — this stack never manages them.
//
// Deploy at resource-group scope into rg-mcp-prod-001:
//   az deployment group what-if -g rg-mcp-prod-001 -f infra/main.bicep -p infra/main.bicepparam
//   az deployment group create  -g rg-mcp-prod-001 -f infra/main.bicep -p infra/main.bicepparam
//
// State lives server-side in ARM deployment history — no state file, nothing
// secret-bearing on disk (this is why the stack moved off Terraform).
////////////////////////////////////////////////////////////////////////////////

targetScope = 'resourceGroup'

// ------------------------------------------------------------------------------
// Existing-infrastructure names (discovered live 2026-07). The subscription and
// resource group come from the deployment scope (`az deployment group -g ...`).
// ------------------------------------------------------------------------------

@description('Existing workload-profiles Container Apps environment (custom VNet, Central US). Referenced, never managed.')
param containerAppEnvironmentName string = 'cae-mcp-prod-002'

@description('Existing container registry holding the doc-intel-analysts image.')
param acrName string = 'formenteramcp'

@description('Shared enterprise key vault holding the doc-intel secrets.')
param keyVaultName string = 'kv-enterprise-shared-001'

@description('Resource group of the shared key vault (a DIFFERENT group — the vault role assignment deploys there via a module).')
param keyVaultResourceGroupName string = 'rg-enterprise-shared-001'

@description('Location for the new resources. Terraform read it off the environment at plan time; ARM needs it at deployment start, so it defaults to the resource group\'s location (same region, Central US). Override only if they ever diverge.')
param location string = resourceGroup().location

// ------------------------------------------------------------------------------
// Image + rollout gating
// ------------------------------------------------------------------------------

@description('Tag of formenteramcp.azurecr.io/doc-intel-analysts to deploy. No default: pin every deploy.')
param imageTag string

@description('Wave 2 gate: false deploys storage + the gate job only; true adds the service and the ingest/maintenance/graph-rebuild jobs (flip only after the NFS bootstrap parity gate passes).')
param deployService bool = false

// ------------------------------------------------------------------------------
// Networking (shared production subnet/NSG — identified, never managed).
// The NSG must live in this deployment's resource group: the two allow rules
// below are authored as child resources of it.
// ------------------------------------------------------------------------------

@description('Resource ID of the environment\'s infrastructure subnet; becomes the storage account\'s only allowed network (needs the Microsoft.Storage service endpoint).')
param infrastructureSubnetId string

@description('Name of the NSG attached to the environment\'s infrastructure subnet, or empty to skip the allow rules entirely. Discovered 2026-07-13: sn-container-apps has NO NSG attached, so nothing filters 445/2049 and there is nothing to add rules to — attaching a new NSG to the shared production subnet is out of scope for this stack. If an NSG is ever attached to the subnet, set this parameter and redeploy. Only NEW allow rules are added; existing rules are never modified.')
param nsgName string = ''

@description('Priority for the outbound 445 allow rule (must not collide with existing rules).')
param nsgRulePrioritySmb int = 3900

@description('Priority for the outbound 2049 allow rule (must not collide with existing rules).')
param nsgRulePriorityNfs int = 3901

// ------------------------------------------------------------------------------
// Storage
// ------------------------------------------------------------------------------

@description('Globally-unique name for the Premium FileStorage account backing the NFS share.')
param storageAccountName string = 'stdocintelanalysts'

@description('NFS file share carrying the evidence/cognee/masters sub-paths.')
param shareName string = 'doc-intel-store'

@description('Provisioned share size in GiB (premium bills on provisioned size).')
param shareQuotaGib int = 200

// ------------------------------------------------------------------------------
// Runtime
// ------------------------------------------------------------------------------

@description('Region for the S3 derived/raw buckets (boto3 AWS_DEFAULT_REGION on containers holding AWS credentials).')
param awsRegion string = 'us-east-1'

@description('Dedicated workload profile the maintenance job runs on. Added via CLI, not this stack — see README.')
param maintenanceWorkloadProfileName string = 'E8'

// ------------------------------------------------------------------------------
// Key Vault secret NAMES (values live only in the vault, never here)
// ------------------------------------------------------------------------------

@description('KV secret name for the Vercel AI Gateway API key.')
param gatewayKeySecretName string = 'doc-intel-gateway-key'

@description('KV secret name for the analysts service bearer token.')
param analystsTokenSecretName string = 'doc-intel-analysts-token'

@description('KV secret name for the S3 reader access key id.')
param awsAccessKeyIdSecretName string = 'doc-intel-aws-access-key-id'

@description('KV secret name for the S3 reader secret access key.')
param awsSecretAccessKeySecretName string = 'doc-intel-aws-secret-access-key'

// ------------------------------------------------------------------------------
// Existing infrastructure — referenced, never managed here
// ------------------------------------------------------------------------------

resource managedEnvironment 'Microsoft.App/managedEnvironments@2025-01-01' existing = {
  name: containerAppEnvironmentName
}

resource acr 'Microsoft.ContainerRegistry/registries@2023-07-01' existing = {
  name: acrName
}

resource nsg 'Microsoft.Network/networkSecurityGroups@2024-05-01' existing = {
  name: nsgName
}

// ------------------------------------------------------------------------------
// Shared values
// ------------------------------------------------------------------------------

var appName = 'doc-intel-analysts'
var appRoot = '/app/agents/doc-intel/analysts' // Dockerfile WORKDIR
var image = '${acr.properties.loginServer}/doc-intel-analysts:${imageTag}'

// The vault lives in another resource group; its URI is deterministic from the
// name, so no cross-group reference is needed to build secret URLs.
var keyVaultUri = 'https://${keyVaultName}${environment().suffixes.keyvaultDns}/'

// Silent-egress guard set (graph/config.py `configure()` + `_assert_gateway_only()`).
// configure() setdefaults these, but the template pins them so a code regression
// cannot silently re-route content off the gateway path. Non-secret only —
// LLM_API_KEY / EMBEDDING_API_KEY are derived at runtime from AI_GATEWAY_API_KEY.
var guardEnv = [
  { name: 'LLM_ENDPOINT', value: 'https://ai-gateway.vercel.sh/v1' }
  { name: 'EMBEDDING_ENDPOINT', value: 'https://ai-gateway.vercel.sh/v1' }
  { name: 'TELEMETRY_DISABLED', value: '1' }
  { name: 'CACHING', value: 'false' }
  { name: 'LLM_INSTRUCTOR_MODE', value: 'tool_call' }
  { name: 'EMBEDDING_MODEL', value: 'text-embedding-3-large' }
  { name: 'EMBEDDING_DIMENSIONS', value: '3072' }
  { name: 'EMBEDDING_MAX_TOKENS', value: '8191' }
]

// One NFS share, three sub-path mounts (KTD3 store layout).
var volumeName = 'doc-intel-store'
var storeVolumes = [
  {
    name: volumeName
    storageType: 'NfsAzureFile'
    storageName: envStorage.name
  }
]
var storeVolumeMounts = [
  { volumeName: volumeName, mountPath: '${appRoot}/.evidence', subPath: 'evidence' }
  { volumeName: volumeName, mountPath: '${appRoot}/.cognee', subPath: 'cognee' }
  { volumeName: volumeName, mountPath: '${appRoot}/.masters', subPath: 'masters' }
]

var tags = {
  initiative: 'doc-intel'
  component: 'analysts'
  stack: 'container-apps'
}

// Shared identity/registry/secret fragments for the service and jobs.
var appIdentity = {
  type: 'UserAssigned'
  userAssignedIdentities: {
    '${identity.id}': {}
  }
}
var acrRegistries = [
  {
    server: acr.properties.loginServer
    identity: identity.id
  }
]

// Key Vault references resolved via the managed identity — no literal values.
var secretGatewayKey = {
  name: 'ai-gateway-api-key'
  identity: identity.id
  keyVaultUrl: '${keyVaultUri}secrets/${gatewayKeySecretName}'
}
var secretAnalystsToken = {
  name: 'analysts-api-token'
  identity: identity.id
  keyVaultUrl: '${keyVaultUri}secrets/${analystsTokenSecretName}'
}
var secretAwsAccessKeyId = {
  name: 'aws-access-key-id'
  identity: identity.id
  keyVaultUrl: '${keyVaultUri}secrets/${awsAccessKeyIdSecretName}'
}
var secretAwsSecretAccessKey = {
  name: 'aws-secret-access-key'
  identity: identity.id
  keyVaultUrl: '${keyVaultUri}secrets/${awsSecretAccessKeySecretName}'
}

// ------------------------------------------------------------------------------
// Identity + IAM — one user-assigned identity shared by the service and jobs
// ------------------------------------------------------------------------------

resource identity 'Microsoft.ManagedIdentity/userAssignedIdentities@2023-01-31' = {
  name: '${appName}-identity'
  location: location
  tags: tags
}

// Key Vault Secrets User on the shared vault — deployed into the vault's
// resource group (rg-enterprise-shared-001) because role assignments must be
// created in the scope they attach to.
module kvSecretsUser 'modules/key-vault-secrets-user.bicep' = {
  name: '${appName}-kv-secrets-user'
  scope: resourceGroup(keyVaultResourceGroupName)
  params: {
    keyVaultName: keyVaultName
    principalId: identity.properties.principalId
  }
}

// Built-in role: AcrPull
var acrPullRoleDefinitionId = subscriptionResourceId(
  'Microsoft.Authorization/roleDefinitions',
  '7f951dda-4ed3-4680-a7ca-43fe172d538d'
)

resource acrPull 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  // Deterministic name (seeded with the identity's resource id, which unlike
  // principalId is known before deployment starts): idempotent re-deploys.
  name: guid(acr.id, identity.id, acrPullRoleDefinitionId)
  scope: acr
  properties: {
    roleDefinitionId: acrPullRoleDefinitionId
    principalId: identity.properties.principalId
    principalType: 'ServicePrincipal'
  }
}

// ------------------------------------------------------------------------------
// Premium NFS file share backing the three doc-intel stores
// (.evidence / .cognee / .masters as sub-paths of one 200 GiB share).
//
// NFS requires "secure transfer required" OFF and a VNet-scoped network rule
// set; the Container Apps environment's infrastructure subnet is the only
// allowed network (it needs the Microsoft.Storage service endpoint — README).
// ------------------------------------------------------------------------------

resource storageAccount 'Microsoft.Storage/storageAccounts@2023-05-01' = {
  name: storageAccountName
  location: location
  kind: 'FileStorage'
  sku: {
    name: 'Premium_LRS'
  }
  properties: {
    // NFS 4.1 does not support encryption in transit via the HTTPS/SMB path;
    // the share is protected by the VNet scoping below instead.
    supportsHttpsTrafficOnly: false
    minimumTlsVersion: 'TLS1_2'
    allowBlobPublicAccess: false
    networkAcls: {
      defaultAction: 'Deny'
      bypass: 'AzureServices'
      virtualNetworkRules: [
        {
          id: infrastructureSubnetId
          action: 'Allow'
        }
      ]
    }
  }
  tags: tags
}

resource fileService 'Microsoft.Storage/storageAccounts/fileServices@2023-05-01' = {
  parent: storageAccount
  name: 'default'
}

resource fileShare 'Microsoft.Storage/storageAccounts/fileServices/shares@2023-05-01' = {
  parent: fileService
  name: shareName
  properties: {
    shareQuota: shareQuotaGib
    enabledProtocols: 'NFS'
    // Azure's default for NFS shares (and what the Terraform stack deployed —
    // azurerm does not expose the setting). Root on the client stays root.
    rootSquash: 'NoRootSquash'
  }
}

// Registers the NFS share with the (unmanaged, existing) environment so apps
// and jobs can mount it by storageName. Child resource on the EXISTING
// environment: Bicep allows `parent:` to point at an `existing` resource, so
// no ownership of the environment is implied.
resource envStorage 'Microsoft.App/managedEnvironments/storages@2025-01-01' = {
  parent: managedEnvironment
  name: volumeName
  properties: {
    nfsAzureFile: {
      server: '${storageAccount.name}.file.${environment().suffixes.storage}'
      shareName: '/${storageAccount.name}/${fileShare.name}'
      accessMode: 'ReadWrite'
    }
  }
}

// ------------------------------------------------------------------------------
// NSG allow rules for Azure Files (SMB 445 / NFS 2049) on the environment's
// infrastructure subnet. The NSG is SHARED PRODUCTION infrastructure: this
// stack only ADDS the two allow rules below (as child resources of the
// existing NSG) and never touches existing rules. Priorities are parameters
// so they can be slotted around what already exists.
// ------------------------------------------------------------------------------

resource nsgRuleSmb445 'Microsoft.Network/networkSecurityGroups/securityRules@2024-05-01' = if (!empty(nsgName)) {
  parent: nsg
  name: 'allow-doc-intel-storage-smb-445'
  properties: {
    priority: nsgRulePrioritySmb
    direction: 'Outbound'
    access: 'Allow'
    protocol: 'Tcp'
    sourcePortRange: '*'
    destinationPortRange: '445'
    sourceAddressPrefix: 'VirtualNetwork'
    destinationAddressPrefix: 'Storage'
  }
}

resource nsgRuleNfs2049 'Microsoft.Network/networkSecurityGroups/securityRules@2024-05-01' = if (!empty(nsgName)) {
  parent: nsg
  name: 'allow-doc-intel-storage-nfs-2049'
  properties: {
    priority: nsgRulePriorityNfs
    direction: 'Outbound'
    access: 'Allow'
    protocol: 'Tcp'
    sourcePortRange: '*'
    destinationPortRange: '2049'
    sourceAddressPrefix: 'VirtualNetwork'
    destinationAddressPrefix: 'Storage'
  }
}

// ------------------------------------------------------------------------------
// The analysts FastAPI service (uvicorn on 8734) — wave 2 only.
//
// Gated behind deployService: wave 1 stands up storage + the gate job, and the
// service deploys only after the NFS bootstrap parity gate passes. Exactly one
// replica: the embedded Kuzu/LanceDB stores are single-writer.
// ------------------------------------------------------------------------------

resource service 'Microsoft.App/containerApps@2025-01-01' = if (deployService) {
  name: appName
  location: location
  tags: tags
  identity: appIdentity
  properties: {
    environmentId: managedEnvironment.id
    workloadProfileName: 'Consumption'
    configuration: {
      activeRevisionsMode: 'Single'
      ingress: {
        external: true
        targetPort: 8734
        allowInsecure: false
        traffic: [
          {
            latestRevision: true
            weight: 100
          }
        ]
      }
      registries: acrRegistries
      secrets: [
        secretGatewayKey
        secretAnalystsToken
        secretAwsAccessKeyId
        secretAwsSecretAccessKey
      ]
    }
    template: {
      scale: {
        minReplicas: 1
        maxReplicas: 1
      }
      volumes: storeVolumes
      containers: [
        {
          name: appName
          image: image
          resources: {
            cpu: 2
            memory: '4Gi'
          }
          // Silent-egress guard pinned on every container (see guardEnv above).
          env: concat(guardEnv, [
            // Hosted mode fails closed: service refuses to start without the token.
            { name: 'ANALYSTS_REQUIRE_AUTH', value: '1' }
            { name: 'AWS_DEFAULT_REGION', value: awsRegion }
            { name: 'AI_GATEWAY_API_KEY', secretRef: 'ai-gateway-api-key' }
            { name: 'ANALYSTS_API_TOKEN', secretRef: 'analysts-api-token' }
            { name: 'AWS_ACCESS_KEY_ID', secretRef: 'aws-access-key-id' }
            { name: 'AWS_SECRET_ACCESS_KEY', secretRef: 'aws-secret-access-key' }
          ])
          volumeMounts: storeVolumeMounts
        }
      ]
    }
  }
}

// ------------------------------------------------------------------------------
// Batch jobs. All four mount the same NFS share via the three sub-path
// mounts. The image has no ENTRYPOINT, so `args` IS the container command
// (Dockerfile convention: plain CMD, jobs override the whole command).
//
//   gate          wave 1 — replica bootstrap down-sync + parity check (NFS gate)
//   ingest        wave 2 — evidence batch ingest (cron authored, disabled)
//   maintenance   wave 2 — index build + compaction on the E8 dedicated profile
//   graph-rebuild wave 2 — cognee graph ingest (service MUST be stopped: Kuzu
//                          is single-writer, an idle service still holds the lock)
// ------------------------------------------------------------------------------

// --- gate (wave 1: NOT gated by deployService) ---------------------------------

resource gateJob 'Microsoft.App/jobs@2025-01-01' = {
  name: '${appName}-gate'
  location: location
  tags: tags
  identity: appIdentity
  properties: {
    environmentId: managedEnvironment.id
    workloadProfileName: 'Consumption'
    configuration: {
      triggerType: 'Manual'
      replicaTimeout: 14400 // full-store S3 down-sync is hours, not minutes
      replicaRetryLimit: 0 // idempotent resume — restart manually after triage
      manualTriggerConfig: {
        parallelism: 1
        replicaCompletionCount: 1
      }
      registries: acrRegistries
      secrets: [
        secretGatewayKey
        secretAwsAccessKeyId
        secretAwsSecretAccessKey
      ]
    }
    template: {
      volumes: storeVolumes
      // ACA has no fsGroup: the NFS sub_path dirs are auto-created root-owned,
      // and the analysts image runs as uid 1000 — the very first gate run hit
      // EACCES exactly as the plan's non-root write check predicted. This init
      // container (root by image default) hands the three mount dirs to the
      // app user before the main container starts. Non-recursive on purpose:
      // instant, and children created by uid 1000 stay owned by it.
      initContainers: [
        {
          name: 'fix-mount-ownership'
          image: 'mcr.microsoft.com/azurelinux/busybox:1.36'
          command: ['sh', '-c', 'chown 1000:1000 /app/agents/doc-intel/analysts/.evidence /app/agents/doc-intel/analysts/.cognee /app/agents/doc-intel/analysts/.masters && echo "mount ownership -> 1000:1000"']
          resources: {
            cpu: json('0.25')
            memory: '0.5Gi'
          }
          volumeMounts: storeVolumeMounts
        }
      ]
      containers: [
        {
          name: 'gate'
          image: image
          resources: {
            cpu: json('1.75')
            memory: '3.5Gi'
          }
          args: ['python', '-m', 'doc_intel_analysts.evidence.replica', '--bootstrap']
          env: concat(guardEnv, [
            { name: 'AWS_DEFAULT_REGION', value: awsRegion }
            { name: 'AI_GATEWAY_API_KEY', secretRef: 'ai-gateway-api-key' }
            { name: 'AWS_ACCESS_KEY_ID', secretRef: 'aws-access-key-id' }
            { name: 'AWS_SECRET_ACCESS_KEY', secretRef: 'aws-secret-access-key' }
          ])
          volumeMounts: storeVolumeMounts
        }
      ]
    }
  }
}

// --- ingest (wave 2) ------------------------------------------------------------

resource ingestJob 'Microsoft.App/jobs@2025-01-01' = if (deployService) {
  name: '${appName}-ingest'
  location: location
  tags: tags
  identity: appIdentity
  properties: {
    environmentId: managedEnvironment.id
    workloadProfileName: 'Consumption'
    configuration: {
      triggerType: 'Manual'
      replicaTimeout: 14400
      replicaRetryLimit: 0
      manualTriggerConfig: {
        parallelism: 1
        replicaCompletionCount: 1
      }
      // Cron authored but DISABLED until batch cadence is proven. NOTE: an ACA
      // job's trigger type cannot be changed in place — enabling this means
      // replacing the job (switch triggerType to 'Schedule', swap the config
      // block below in, then delete the job and re-deploy).
      // scheduleTriggerConfig: {
      //   cronExpression: '0 6 * * *'
      //   parallelism: 1
      //   replicaCompletionCount: 1
      // }
      registries: acrRegistries
      secrets: [
        secretGatewayKey
        secretAwsAccessKeyId
        secretAwsSecretAccessKey
      ]
    }
    template: {
      volumes: storeVolumes
      containers: [
        {
          name: 'ingest'
          image: image
          resources: {
            cpu: 2
            memory: '4Gi'
          }
          // A source flag (--manifest / --prefix) is REQUIRED at start time — see
          // README "Running ingest" for the `az containerapp job start --args`
          // override; these template args alone exit with an argparse error.
          args: ['python', '-m', 'doc_intel_analysts.evidence.ingest', '--max-new', '250']
          env: concat(guardEnv, [
            { name: 'AWS_DEFAULT_REGION', value: awsRegion }
            { name: 'AI_GATEWAY_API_KEY', secretRef: 'ai-gateway-api-key' }
            { name: 'AWS_ACCESS_KEY_ID', secretRef: 'aws-access-key-id' }
            { name: 'AWS_SECRET_ACCESS_KEY', secretRef: 'aws-secret-access-key' }
          ])
          volumeMounts: storeVolumeMounts
        }
      ]
    }
  }
}

// --- maintenance (wave 2, E8 dedicated profile) ----------------------------------

resource maintenanceJob 'Microsoft.App/jobs@2025-01-01' = if (deployService) {
  name: '${appName}-maintenance'
  location: location
  tags: tags
  identity: appIdentity
  properties: {
    environmentId: managedEnvironment.id
    workloadProfileName: maintenanceWorkloadProfileName
    configuration: {
      triggerType: 'Manual'
      replicaTimeout: 21600 // FTS rebuild + full compaction
      replicaRetryLimit: 0
      manualTriggerConfig: {
        parallelism: 1
        replicaCompletionCount: 1
      }
      registries: acrRegistries
      secrets: [
        secretGatewayKey
      ]
    }
    template: {
      volumes: storeVolumes
      containers: [
        {
          name: 'maintenance'
          image: image
          resources: {
            cpu: 4
            memory: '32Gi' // dedicated profile: raise freely within the E8 node
          }
          args: ['python', '-m', 'doc_intel_analysts.evidence.ingest', '--maintain']
          // No AWS credentials: maintenance touches only the local stores.
          env: concat(guardEnv, [
            { name: 'AI_GATEWAY_API_KEY', secretRef: 'ai-gateway-api-key' }
          ])
          volumeMounts: storeVolumeMounts
        }
      ]
    }
  }
}

// --- graph-rebuild (wave 2) -------------------------------------------------------

resource graphRebuildJob 'Microsoft.App/jobs@2025-01-01' = if (deployService) {
  name: '${appName}-graph-rebuild'
  location: location
  tags: tags
  identity: appIdentity
  properties: {
    environmentId: managedEnvironment.id
    workloadProfileName: 'Consumption'
    configuration: {
      triggerType: 'Manual'
      replicaTimeout: 21600 // cognify over the full corpus is hours
      replicaRetryLimit: 0
      manualTriggerConfig: {
        parallelism: 1
        replicaCompletionCount: 1
      }
      registries: acrRegistries
      secrets: [
        secretGatewayKey
        secretAwsAccessKeyId
        secretAwsSecretAccessKey
      ]
    }
    template: {
      volumes: storeVolumes
      containers: [
        {
          name: 'graph-rebuild'
          image: image
          resources: {
            cpu: 2
            memory: '4Gi'
          }
          args: ['python', '-m', 'doc_intel_analysts.graph.ingest']
          // graph/ingest.py reads parsed docs from the derived bucket AND writes
          // its run ledger back to it (_s3.put_object) — the AWS pair is required.
          env: concat(guardEnv, [
            { name: 'AI_GATEWAY_API_KEY', secretRef: 'ai-gateway-api-key' }
            { name: 'AWS_DEFAULT_REGION', value: awsRegion }
            { name: 'AWS_ACCESS_KEY_ID', secretRef: 'aws-access-key-id' }
            { name: 'AWS_SECRET_ACCESS_KEY', secretRef: 'aws-secret-access-key' }
          ])
          volumeMounts: storeVolumeMounts
        }
      ]
    }
  }
}

// ------------------------------------------------------------------------------
// Outputs
// ------------------------------------------------------------------------------

@description('External ingress URL of the analysts service (empty until deployService = true).')
output serviceUrl string = deployService ? 'https://${service!.properties.configuration.ingress.fqdn}' : ''

@description('Premium FileStorage account backing the NFS share.')
output storageAccountName string = storageAccount.name

@description('NFS share carrying the evidence/cognee/masters sub-paths.')
output shareName string = fileShare.name

@description('Principal id of the shared user-assigned identity (for the R10 RBAC enumeration).')
output identityPrincipalId string = identity.properties.principalId

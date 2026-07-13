////////////////////////////////////////////////////////////////////////////////
// Key Vault Secrets User grant for the analysts identity.
//
// Split into a module because the shared vault (kv-enterprise-shared-001)
// lives in a DIFFERENT resource group (rg-enterprise-shared-001): a role
// assignment scoped to the vault must be deployed in the vault's resource
// group, so main.bicep invokes this with
// `scope: resourceGroup(keyVaultResourceGroupName)`.
////////////////////////////////////////////////////////////////////////////////

@description('Name of the existing shared key vault (must be in this module\'s target resource group).')
param keyVaultName string

@description('Principal id of the user-assigned identity being granted secret read.')
param principalId string

// Built-in role: Key Vault Secrets User
var keyVaultSecretsUserRoleDefinitionId = subscriptionResourceId(
  'Microsoft.Authorization/roleDefinitions',
  '4633458b-17de-408a-b874-0445c86b69e6'
)

resource keyVault 'Microsoft.KeyVault/vaults@2023-07-01' existing = {
  name: keyVaultName
}

resource secretsUser 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  // Deterministic name: same vault + principal + role always yields the same
  // guid, so re-deploys are idempotent instead of stacking duplicates.
  name: guid(keyVault.id, principalId, keyVaultSecretsUserRoleDefinitionId)
  scope: keyVault
  properties: {
    roleDefinitionId: keyVaultSecretsUserRoleDefinitionId
    principalId: principalId
    // Pinning the type avoids the AAD replication race on fresh identities.
    principalType: 'ServicePrincipal'
  }
}

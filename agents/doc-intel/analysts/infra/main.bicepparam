// Example parameters — committed. NON-SECRET values only (resource names/ids);
// the real subnet id and NSG name are documented in README.md "Prerequisites".
// Secrets never appear here: the templates read them from Key Vault by name.
using './main.bicep'

// Pin every deploy to an explicit image tag.
param imageTag = '503b5f0'

// Resource ID of the environment's infrastructure subnet (needs the
// Microsoft.Storage service endpoint — README).
param infrastructureSubnetId = '/subscriptions/67a8e488-3328-4e25-9202-952679ad9744/resourceGroups/rg-mcp-prod-001/providers/Microsoft.Network/virtualNetworks/vnet-mcp-prod/subnets/sn-container-apps'

// NSG attached to that subnet. Check existing rule priorities before accepting
// the 3900/3901 defaults (nsgRulePrioritySmb / nsgRulePriorityNfs).
param nsgName = '' // no NSG on sn-container-apps (verified 2026-07-13); set + redeploy if one is ever attached

// Wave 2 gate — leave false for wave 1; wave 2 overrides on the CLI:
//   az deployment group create ... -p deployService=true
param deployService = false

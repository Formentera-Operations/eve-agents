// Example parameters — committed. NON-SECRET values only (resource names/ids);
// the real subnet id and NSG name are documented in README.md "Prerequisites".
// Secrets never appear here: the templates read them from Key Vault by name.
using './main.bicep'

// Pin every deploy to an explicit image tag.
param imageTag = 'REPLACE_ME'

// Resource ID of the environment's infrastructure subnet (needs the
// Microsoft.Storage service endpoint — README).
param infrastructureSubnetId = '/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/rg-mcp-prod-001/providers/Microsoft.Network/virtualNetworks/REPLACE_ME-vnet/subnets/REPLACE_ME-subnet'

// NSG attached to that subnet. Check existing rule priorities before accepting
// the 3900/3901 defaults (nsgRulePrioritySmb / nsgRulePriorityNfs).
param nsgName = 'REPLACE_ME-nsg'

// Wave 2 gate — leave false for wave 1; wave 2 overrides on the CLI:
//   az deployment group create ... -p deployService=true
param deployService = false

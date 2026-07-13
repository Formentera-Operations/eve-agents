# doc-intel analysts — Azure Container Apps stack (Bicep)

Hosts the analysts FastAPI service and four batch jobs on the existing
`cae-mcp-prod-002` environment (`rg-mcp-prod-001`, Central US). The
environment, ACR (`formenteramcp`), and vault (`kv-enterprise-shared-001`)
are referenced as `existing` resources — never managed here.

State lives server-side in ARM deployment history — no state file, nothing
secret-bearing on disk. (This is why the stack moved off Terraform, whose
state captured the Files storage account key.)

## Prerequisites

1. KV secrets exist in `kv-enterprise-shared-001`: `doc-intel-gateway-key`,
   `doc-intel-analysts-token`, `doc-intel-aws-access-key-id`,
   `doc-intel-aws-secret-access-key`.
2. Image pushed: `formenteramcp.azurecr.io/doc-intel-analysts:<tag>`.
3. The environment's infrastructure subnet has the `Microsoft.Storage`
   service endpoint (`az network vnet subnet show ... --query serviceEndpoints`;
   add with `az network vnet subnet update --service-endpoints Microsoft.Storage`).
4. `infra/main.bicepparam` filled in: `imageTag`, `infrastructureSubnetId`.
   The file is committed — non-secret resource names/ids only.
5. NSG: `sn-container-apps` has **no NSG attached** (verified 2026-07-13), so
   `nsgName` stays `''` and the 445/2049 allow rules are skipped — nothing
   filters those ports today. If an NSG is ever attached to the subnet, set
   `nsgName` and redeploy (check existing rule priorities before accepting
   the 3900/3901 defaults).

## E8 workload profile (CLI, not Bicep)

This stack does not manage the environment, so it cannot add profiles to it.
Check for existing Dedicated profiles first — the FIRST Dedicated profile in
an environment starts the plan management fee (~$70/mo):

```sh
az containerapp env show -n cae-mcp-prod-002 -g rg-mcp-prod-001 \
  --query properties.workloadProfiles
az containerapp env workload-profile add -n cae-mcp-prod-002 -g rg-mcp-prod-001 \
  --workload-profile-name E8 --workload-profile-type E8 --min-nodes 0 --max-nodes 1
```

`--min-nodes 0`: E8 node-hours bill only while the maintenance job runs.

## Reviewing changes (replaces `terraform plan`)

Run all commands from `agents/doc-intel/analysts/`. Before any apply, `what-if`
is the pre-apply cost/blast-radius review:

```sh
az deployment group what-if -g rg-mcp-prod-001 -f infra/main.bicep -p infra/main.bicepparam
```

## Wave 1 — storage + gate

```sh
az deployment group create -g rg-mcp-prod-001 -f infra/main.bicep -p infra/main.bicepparam   # deployService defaults to false
az containerapp job start -n doc-intel-analysts-gate -g rg-mcp-prod-001
```

Creates the Premium NFS share (200 GiB, VNet-scoped), the environment
storage mount, the
identity + role assignments, and the gate job.

**Single-writer cutover:** the laptop stops writing to the S3-replicated
stores at the FIRST Azure job write. From the gate run onward, Azure owns
the stores.

### Gate checks — ALL FOUR must pass before wave 2

The NFS gate is four blocking checks, not one. The gate job's default args
run only check 1; checks 2–4 reuse the same job with `--args` overrides.

**1. Replica parity** (the job's default args): down-syncs the four S3
prefixes, exits nonzero on per-key parity failure (idempotent: re-run
resumes).

**2. Latency benchmark** — the plan's hard go/no-go. Run against the
mounted lance root, write results to the mount, then pull and compare:

```sh
az containerapp job start -n doc-intel-analysts-gate -g rg-mcp-prod-001 \
  --args "python" "-m" "doc_intel_analysts.evidence.latency_bench" \
         "--root" "/app/agents/doc-intel/analysts/.evidence/lance" \
         "--out" "/app/agents/doc-intel/analysts/.evidence/nfs-gate.json"
```

Pass criterion: **every row has `within_60s_tool_budget: true`**, compared
against `benchmark/results/2026-07-11-phase2-s3-latency.json`'s local
column. Commit the results JSON to `benchmark/results/` either way. Any op
over budget = STOP: amend the migration decision record and switch to the
documented VM/AKS fallback plan — do not build wave 2 on a failed gate.

**3. Non-root NFS write check** (uid 1000, no fsGroup on ACA — NFS
ownership is real POSIX):

```sh
az containerapp job start -n doc-intel-analysts-gate -g rg-mcp-prod-001 \
  --args "python" "-c" "import pathlib
for m in ('.evidence', '.cognee', '.masters'):
    p = pathlib.Path('/app/agents/doc-intel/analysts', m, '.write-check')
    p.write_text('ok'); p.unlink(); print(f'{m}: write ok')"
```

The point is a successful write+delete as the container user (uid 1000)
on all three mounts; an `EACCES` here means the share's POSIX ownership
needs fixing before anything else runs.

**4. Kuzu-on-NFS lock check**: open the synced graph store on the mount,
confirm lock acquisition/release and a basic read (embedded-DB-on-NFS
locking is the open risk the brain decision flags). Locate the Kuzu
database dir under `.cognee` (`find /app/agents/doc-intel/analysts/.cognee
-maxdepth 3 -iname '*kuzu*'`), then open it with `python -c "import kuzu;
kuzu.Database('<path>')"` via the same `--args` override, twice in
succession (second open after first exits proves release).

Deferred follow-up (also noted in the plan's KTD6 spirit): fold checks 2–4
into a single scripted gate command so the sequence cannot be skipped.

## Wave 2 — service + remaining jobs

```sh
az deployment group create -g rg-mcp-prod-001 -f infra/main.bicep -p infra/main.bicepparam -p deployService=true
```

Adds the service (external ingress :8734, auth required, 1 replica pinned)
and the ingest / maintenance / graph-rebuild jobs.

### Kuzu sequencing (single-writer)

Stop the service before any graph job — an idle service still holds the
Kuzu lock:

```sh
az containerapp stop -n doc-intel-analysts -g rg-mcp-prod-001
az containerapp job start -n doc-intel-analysts-graph-rebuild -g rg-mcp-prod-001
az containerapp start -n doc-intel-analysts -g rg-mcp-prod-001   # after completion
```

### Running ingest

The template args (`--max-new 250`) need a source flag at start time:

```sh
az containerapp job start -n doc-intel-analysts-ingest -g rg-mcp-prod-001 \
  --args "python" "-m" "doc_intel_analysts.evidence.ingest" \
         "--prefix" "<raw-bucket-prefix>" "--max-new" "250"
```

Run maintenance (`--maintain`) between batches. The cron trigger is
authored but commented in `main.bicep`; ACA trigger types are immutable, so
enabling it replaces the job.

## R10 — RBAC enumeration

Compare every principal below against the S3 raw-bucket reader list; any
Azure-side principal not on it is an escalation. (The deployment name
defaults to the template filename, `main`.)

```sh
az role assignment list --scope $(az deployment group show -g rg-mcp-prod-001 -n main --query properties.outputs.storageAccountName.value -o tsv | xargs -I{} az storage account show -n {} -g rg-mcp-prod-001 --query id -o tsv) -o table
az role assignment list --scope /subscriptions/$ARM_SUBSCRIPTION_ID/resourceGroups/rg-mcp-prod-001 -o table
az role assignment list --scope $(az keyvault show -n kv-enterprise-shared-001 -g rg-enterprise-shared-001 --query id -o tsv) -o table   # vault + per-secret scopes
az role assignment list --scope $(az monitor log-analytics workspace list -g rg-mcp-prod-001 --query [0].id -o tsv) -o table             # env's workspace
```

## Cost

~$80–160/mo: Premium share 200 GiB provisioned (~$32), service 1 replica
Consumption (~$25–60), episodic job vCPU-seconds, plus the Dedicated plan
management fee once the E8 profile exists (waived only if the environment
already has a Dedicated profile — check before adding).

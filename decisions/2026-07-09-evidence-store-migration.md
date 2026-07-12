# Evidence-store migration off the laptop — S3 becomes source of truth

**Status:** ACCEPTED (Rob, 2026-07-08) as a four-phase plan. Phase 1
executed and verified 2026-07-09. **Phase 2 host choice RESOLVED
2026-07-11 — Azure Container App with a local replica; direct-S3
disqualified by benchmark (see "Phase 2 resolution" below).**

**Decision recorded:** the Westlake evidence store (61 GB Lance + 2.4 GB
parsed output under `agents/doc-intel/analysts/.evidence/`) migrates off
Rob's MacBook. `s3://formentera-welldrive-derived` becomes the source of
truth; the laptop copy becomes a disposable replica. Future ingest and
maintenance run in Azure, not on a personal machine.

**Context:** ingest at Westlake scale (37,718 objects) empirically exceeded
the laptop. Three kernel watchdog panics (Jul 7 13:36, Jul 7 23:01, Jul 8
07:07), one jetsam-forced restart mid-ingest (Jul 8 20:05), and four jetsam
kills during final maintenance (Jul 9 04:57–05:40). The batch-driver
remediation (`dbdf9b3`, `4d0a16f`) was enough to *finish the pass* — all
37,718 objects, 0 failures\* — but not enough to *maintain the store*:

> \* Post-decision correction: that failure counter was structurally blind
> to parse-layer failures — 9 documents were recorded as terminal skips,
> invisible to the metric (fixed in PR #12; see
> `../docs/solutions/logic-errors/ingest-ledger-conflates-parse-failures-with-skips.md`).
> The migration conclusions are unaffected.

- `pages` (51 GB, 280,016 rows) cannot be compacted on this machine. The
  raw `compact_files` API Rust-panics on a pylance 0.36 decode bug (any
  parameters; also panics on the blob-free `chunks` table, so it is the API
  path, not the data). The lancedb `table.optimize()` path works — it
  compacted `chunks` to 1 fragment at a 3.3 GB peak — but needs >21 GB for
  `pages` and gets jetsam-killed every attempt on a 38 GB machine.
- The store is fully indexed and retrieval-verified, but `pages` sits at
  12,851 fragments (grep-scan latency cost), and every future re-ingest
  pass re-runs this same fight.
- Until Phase 1 executes, the only copy of a multi-day, repeatedly
  crash-interrupted ingest lives on one laptop that panics under memory
  pressure. That is the urgency.

**The phases:**

1. **S3 sync (now):** `aws s3 sync` of `.evidence/lance/` and
   `.evidence/parsed/` to `s3://formentera-welldrive-derived/runs/doc-intel/
   evidence/`. Verify object counts + bytes against local before declaring
   S3 authoritative. Fragment-heavy `pages` syncs fine — this phase moves
   bytes, not table structure.
2. **Retrieval rehome (open sub-decision):** (a) point `lance_root` directly
   at S3 (LanceDB reads `s3://` natively) vs (b) a small Azure Container App
   hosting a local replica. Benchmark direct-S3 query latency first; choose
   (b) only if latency is unacceptable for the agent's read path.
3. **Vercel team scope + gateway billing** move from Rob's personal scope
   (`doc-intel-dev`) to the formentera team — pre-existing open item, folded
   in here because prod deploy depends on it.
4. **Future ingests as an Azure Container Apps Job** with service
   credentials — kills OIDC token babysitting, and provides the
   high-memory environment where `pages` compaction (and every future
   full maintenance) actually fits.

**Alternatives considered:**
- *Keep the laptop as home, treat S3 as backup:* rejected — four memory
  kills in three days *after* the Spotlight exclusion and batch-driver
  remediation; full maintenance is provably impossible locally.
- *Bigger local machine:* rejected — the stack is Azure-first, the
  Container Apps Job pattern already exists in-house, and a personal
  machine remains a single point of failure regardless of RAM.
- *Upgrade pylance to fix the compaction panic:* orthogonal, not
  sufficient — the working code path still needs >21 GB for `pages`, which
  no pylance version changes. May still be worth doing on the server;
  dependency change needs explicit approval.

**Trade-offs accepted:** S3 storage cost is trivial (~$1.50/mo at 61 GB);
Phase 2 may add read latency vs local NVMe (hence the benchmark gate);
two copies exist during the transition.

**Phase 2 resolution (2026-07-11, Rob):** option (b) — Azure Container App
hosting a local replica, bootstrapped by the Phase 1 sync script pointed
downward (`aws s3 sync` S3→container disk at startup; ~100 GB disk to
leave growth room). S3 remains source of truth; the replica is disposable.

The benchmark (real `EvidenceRetriever` query code, read-only store shim,
sampled stored vector as query embedding, 90 s per-call cap vs the 60 s
tool budget; laptop → us-east-1) disqualified direct-S3 decisively:

| Op | Local NVMe (warm) | Direct-S3 (cold → warm) |
|---|---|---|
| open + count 4 tables | 0.003 s | 1.7 s → 0.01 s ✅ |
| vector search (chunks) | 0.97 s | **>90 s even warm** ❌ |
| fts search (chunks) | 0.004 s | 19.2 s → 0.93 s ✅ warm |
| grep (pages scan) ×2 | 2.5–2.8 s | **>90 s** ❌ |
| find_documents | 0.003 s | 8.2 s → 5.1 s ⚠️ |
| document_status | 0.03 s | 28.2 s → 8.9 s ⚠️ |
| get_page text / +blob / doc pages | 0.04–4.0 s | **>90 s all three** ❌ |

Two independent failure classes: (1) the pre-compaction `pages` table's
12,851 fragments make even **point reads** time out — per-fragment
round-trips dominate query planning, so Azure's better network cannot
rescue it pre-Phase-4; (2) the chunks vector index never completed a
query under 90 s even warm — per-query index reads exceed what any
plausible bandwidth uplift closes against a 60 s *ceiling* (the product
needs seconds). The local-NVMe column is green across the board and
network-independent; the replica inherits it wholesale. Direct-S3 may be
cheaply re-tested from inside Azure after Phase 4 compaction, but nothing
waits on it. Raw data: benchmark run 2026-07-11, results JSON archived
with the session; methodology reproducible from this table.

Hosting note (2026-07-11): Vercel offers no comparable runtime — Fluid
Compute caps at 800 s / 4 GB with no persistent volumes, versus the
service's multi-hour jobs, 21–24 GB ingest peaks, and 61 GB replica. The
seam decision's split (eve agent on Vercel, Python service on container
infra) is also Vercel's own recommended shape. AWS colocation (Fargate
beside the S3 bucket) would make replica bootstrap intra-region, but
Azure-first policy and the existing Container Apps patterns keep ACA;
cross-cloud sync (~$5–6, minutes, at startup only) is the accepted cost.

**Supersedes:** nothing — extends `2026-07-05-doc-intel-seam.md` (evidence
store as application-owned layer) with an infrastructure home.
**Owner:** Rob (phase timing; Phase 2 resolved as above).

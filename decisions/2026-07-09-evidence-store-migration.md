# Evidence-store migration off the laptop — S3 becomes source of truth

**Status:** ACCEPTED (Rob, 2026-07-08) as a four-phase plan. Phase 2's host
choice is the one open sub-decision. Execute Phase 1 promptly.

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
37,718 objects, 0 failures — but not enough to *maintain the store*:

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

**Supersedes:** nothing — extends `2026-07-05-doc-intel-seam.md` (evidence
store as application-owned layer) with an infrastructure home.
**Owner:** Rob (Phase 2 host choice, phase timing).

# Five Pragmatic, High-Leverage Bets for Formentera’s `doc-intel`

*Method: I read the requested architecture, decisions, runtime code, evals, and benchmarks; generated 30 candidates; then ranked them on Formentera utility, accretion, novelty, reliability, delivery complexity, technical debt, and overlap with accepted or deferred decisions.*

## 1. Ship a Proof-Carrying WellDrive Evidence Desk

### What it is

Turn the successful local prototype into an always-on, Teams-accessible production service whose user-facing output is a structured set of verified claims—not unconstrained prose. Each claim carries either page evidence or an ingest-ledger status, plus an explicit coverage certificate describing what was and was not searched.

### How it works technically

Complete Phases 2–4 of `decisions/2026-07-09-evidence-store-migration.md`: benchmark direct-S3 LanceDB access first, use an Azure-hosted local replica only if latency requires it, run ingest and compaction as an Azure Container Apps Job, and move the eve deployment and AI Gateway billing into the Formentera Vercel team.

Add `agent/channels/teams.ts` using eve’s native Teams channel, replacing the current production-inert `placeholderAuth()` posture in `agent/channels/eve.ts` with single-tenant identity and private service-to-service authentication for `DOC_INTEL_ANALYSTS_URL`.

Then make the citation contract structural:

- Add an `agent/hooks/evidence_registry.ts` hook that observes successful results from `read_evidence`, `read_parsed_document`, `query_knowledge_graph`, and `check_document_status`, recording the pages and ledger rows actually seen in durable per-session state.
- Add a `finalize_answer` tool with a Zod schema for `claims[]`, `supports[]`, calculations, and `coverage`. It rejects page citations absent from the session registry, requires direct claims to quote a supporting span, and requires calculated claims to identify verified operands and a deterministic formula.
- Represent ledger claims separately as `{s3key, status, reason, ledger_as_of}`. For vision findings, bind the claim to the page ID, screenshot checksum, question, and vision result.
- Have the Teams/client path request the same per-turn structured output schema and render only the finalized object as an Adaptive Card. Source cards should deep-link through the existing `welldrive-files` MCP or another authenticated viewer to the exact page.
- Keep this per-turn envelope ephemeral initially. Do not preempt the deliberately deferred answer ledger in `decisions/2026-07-07-context-layer-answer-ledger.md`; revisit cross-session persistence only after production Agent Runs traces exist.

### Why it is accretive for Formentera

This changes the internal perception from “an impressive laptop chatbot” to “the trusted WellDrive evidence desk.” Engineers get answers inside Teams, data management gets traceable scope and freshness, and every downstream workflow receives machine-readable proof rather than prose it must trust.

The coverage certificate is especially valuable in this corpus: it can distinguish “not found in indexed Westlake as of this ledger watermark” from “not found in the 500-file non-Westlake sample,” while exposing skipped and failed candidates instead of burying them in caveats.

### Implementation sketch

1. Deploy the existing FastAPI service from `analysts/service.py` privately in Azure and run the current six evals plus retrieval benchmarks against both candidate storage configurations.
2. Implement the session evidence registry, finalization schema, page/ledger validators, and adversarial unit tests.
3. Add the Teams channel, source cards, tenant authentication, and role-aware document access.
4. Pilot with a small Operations/Data group; require the existing ≥23/25 benchmark bar, all six evals, zero unregistered citations, and measured availability/latency targets before broad rollout.
5. Only then revisit persistent verified-answer memory.

### Rationale for confidence

Confidence is very high. The difficult capability—finding correct facts with valid pages—already scored 25/25 and survived adversarial citation verification. FastAPI already centralizes `/analyze`, `/graph/*`, and `/evidence/*`; S3 is already authoritative; eve already supplies Teams, durable sessions, structured outputs, hooks, and HITL. The remaining work is infrastructure and enforcement rather than retrieval research. The main uncertainty is direct-S3 query latency, and the accepted migration decision already defines a benchmark-driven fallback.

## 2. Build a Cited AFE-to-Actual Cost Assurance Mart

### What it is

Create a narrow, production-grade data product that extracts versioned AFE facts from WellDrive, joins them to actual financial measures from EnergyLink, AtScale, and Snowflake, and flags material variances with source-page proof.

### How it works technically

Add an open, versioned AFE schema under `references/fact-schemas/` covering AFE number, supplement/revision, effective date, well, gross and net estimate, working interest, and cost-line categories. Generate extraction behavior from that schema, following the same data-driven pattern used by `references/analyst-classes.json` and `analysts/agent.py`.

The batch path should:

- Select only new or changed AFE documents from the evidence ledger in `evidence/store.py`.
- Read relevant pages from the evidence store and run the financial analyst with strict structured output.
- Validate every extracted field against its cited page before publication.
- Resolve wells and organizations to Snowflake master identities using the same principles already implemented in `graph/individuals.py`.
- Preserve `source_s3key`, page, source checksum/ETag, extraction-schema version, and model version on every record.
- Build explicit AFE supersession chains so supplements and revisions are not double-counted.

Publish append-only JSON or Parquet under the derived S3 bucket, then use a conventional medallion flow in Snowflake: raw extraction records → typed dbt staging models → an `fct_well_afe_actual_variance` mart. Actuals should come through allow-listed, read-only EnergyLink and AtScale connections. Variance calculations belong in SQL or a deterministic tool—not in model arithmetic. Power BI consumes the mart; Teams receives only threshold breaches.

This is source-fact persistence, not the deferred answer ledger: records are independently queryable document facts keyed to source bytes, regardless of which user question caused their extraction.

### Why it is accretive for Formentera

This is the shortest path from doc-intel’s demonstrated accuracy to measurable financial value. It can expose overruns, stale AFE baselines, supplement confusion, gross-versus-net mistakes, working-interest mismatches, and partner-billing anomalies while letting Finance or Operations open the exact AFE page behind a number.

It also converts document intelligence into a familiar Formentera data product—Snowflake, dbt, AtScale, and Power BI—so the value compounds beyond agent conversations.

### Implementation sketch

1. Use benchmark questions q01–q03, q11, q15, q16, q18, and q19 as the initial extraction gold set.
2. Pilot one asset team with AFE header totals, working interest, supplement identity, and four high-level cost categories.
3. Establish deterministic version/supersession rules with Finance before joining actuals.
4. Add one EnergyLink/AtScale actual-cost measure and reconcile at well/AFE level before attempting account-level mapping.
5. Publish a Power BI exception page and a scheduled Teams digest; keep any write-back or PatchOps creation behind explicit approval.

### Rationale for confidence

Confidence is high. AFE questions are already among the strongest benchmark surfaces, including multi-document comparisons and table traps such as gross versus net and line item versus subtotal. The ontology pipeline already proves Snowflake master reconciliation, and the company already has the required financial and semantic interfaces. The main risks are accounting-category mapping and document-version semantics; both are bounded business-rule problems that should be solved with versioned tables and SME sign-off, not additional agent autonomy.

## 3. Create an NPT Learning Loop and Offset-Well Briefing Engine

### What it is

Turn operational incidents buried in daily reports, frac tickets, EOW reports, and completion documents into a cited event memory. Use that memory to produce pre-job briefs showing relevant analog wells, recurring failure modes, vendors involved, prior mitigations, and corroborating SCADA or PatchOps context.

### How it works technically

Define a narrow operational-event schema containing well master ID, phase, timestamp, measured depth, symptom, documented cause, action taken, downtime, vendor, outcome, source key/page, and source checksum. Keep three evidence statuses distinct: `documented`, `correlated`, and `inferred`.

Use the existing architecture rather than creating a fourth retrieval engine:

- Nominate event-dense documents through `search_evidence` and exact grep.
- Extract typed events with the drilling and completions analyst classes generated in `analysts/agent.py`.
- Validate citations through the proof contract from Idea 1.
- Persist verified event facts to a Snowflake staging/mart layer.
- Feed only those nominated documents into `graph/ingest.py --from-evidence`, preserving selective enrichment instead of brute-forcing telemetry-heavy documents.
- Query SCADA/IoT and PatchOps for bounded time windows around an event. Aggregate telemetry outside the model context; store references and calculated features rather than pushing raw high-frequency data into Cognee or LanceDB.
- Resolve analog wells using Snowflake master attributes, then use the graph for entity/vendor recall and the evidence store for page-level proof.

The output should be a pre-job brief, not an autonomous operating recommendation. Creating a PatchOps item or sending a prescriptive instruction should remain a human-approved action.

### Why it is accretive for Formentera

The current graph already proves cross-pad vendor conformance, while the eval corpus contains concrete incidents such as stuck tubing at 9,020 ft and the Bull Mountain wireline parting. Structuring those lessons creates institutional memory across asset teams and reduces reliance on who remembers a similar job.

The company-facing result is compelling: “Before this operation, show me the closest analogs, what went wrong, what worked, and the pages proving it.” That is more valuable than generic archive search while remaining grounded and reviewable.

### Implementation sketch

1. Build a 20-event gold set beginning with the incidents locked into `evidence-coverage.eval.ts`, `graph-pad-tandem.eval.ts`, and `graph-wildcat-tandem.eval.ts`.
2. Implement deterministic event validation and publish `stg_doc_intel__operational_event` and `mart_npt_event`.
3. Add read-only PatchOps and aggregated SCADA access for event-window corroboration.
4. Pilot one workflow—stuck pipe/wireline incidents or completion-stage failures—and generate briefs for upcoming analogous work.
5. Require an Operations SME to score event accuracy, analog relevance, and whether each claimed mitigation is documented rather than inferred.

### Rationale for confidence

Confidence is high on value and medium-high on delivery. The repository already demonstrates the essential pieces: event-bearing evidence, cross-document graph recall, master-verified entities, and page verification. The largest risk is false causal attribution when timestamps or narratives are incomplete. The explicit evidence-status taxonomy, bounded telemetry windows, and human gate keep that risk visible. Starting with one incident class avoids turning the graph into an ungoverned operational ontology.

## 4. Turn the Ingest Ledger into a Continuous Well-File Readiness and Change Radar

### What it is

Move from a periodically refreshed archive to a proactive control tower that reports new or changed well files, ingest failures, deferred documents, and missing lifecycle-required records. Deliver only material changes to Teams.

### How it works technically

The current ledger is excellent for current state but overwrites document history, and `ledger_as_of` is only a proxy for the last pass. Extend the ingest model with an append-only run manifest containing `run_id`, prior and new checksum, observed timestamp, authoritative `entry_type`, disposition, parser-policy version, and publication status.

Use `evidence/ingest.py` as the delta engine:

- Continue ETag fast-forwarding and ledger-last settlement.
- Fetch S3 object metadata only for new or changed keys so routing remains based on authoritative `entry_type`, never filenames.
- Build and validate a versioned evidence/graph release, then atomically advance a published-version pointer. This avoids exposing the cross-table partial state that `evidence/store.py` documents during an in-flight upsert.
- Run the retrieval benchmark, core answer canaries, and six deterministic evals before promotion.
- Expand from full Westlake coverage to South Texas and Griffin one asset team at a time after the Azure job is stable.

Add an SME-owned `references/well-file-readiness.yml` defining required document classes by jurisdiction, well lifecycle phase, and internal handoff. Combine Snowflake well status with manifest/evidence metadata and the ingest ledger to distinguish:

- required and indexed;
- present but deferred or failed;
- present but stale or superseded;
- genuinely missing as of the published run.

An eve schedule can then send a conditional Teams digest for new AFEs, permits/W15s, frac or completion closeouts, readiness gaps, and ingest failures. No changes means no message.

### Why it is accretive for Formentera

This makes doc-intel proactive. Operations learns that a new completion report or AFE supplement arrived without asking; Data Management gets a live quality queue; regulatory and well-handover reviews get a repeatable completeness report rather than a manual folder audit.

It also fixes a subtle trust problem: absence claims become tied to an atomic published corpus version rather than a last-write watermark that might reflect an interrupted pass.

### Implementation sketch

1. Add append-only run/delta records and an atomic published-version pointer without changing the current ledger’s status contract.
2. Deploy nightly Azure jobs for Westlake and validate blue/green promotion under concurrent reads.
3. Add two initial watchpacks: material document changes and ingest failures/skips.
4. Build one readiness checklist with Regulatory/Operations—for example completion closeout or ND permit/W15 readiness.
5. Add South Texas and Griffin only after cost, duration, and benchmark gates pass at Westlake scale.

### Rationale for confidence

Confidence is very high. ETag-driven resumption, terminal-versus-retriable status, snapshots, and crash reconciliation already exist and have survived multi-day production-scale ingestion. The required new mechanism is mostly append-only history, release promotion, and business rules. The primary dependency is SME ownership of the readiness matrix; without that, the change feed still delivers value, but “required document” conclusions should not be invented by the model.

## 5. Build a Demand-Weighted Coverage Flywheel

### What it is

Use real unanswered questions and ledgered skips to decide which blind spots deserve engineering effort next. Expand coverage one format or modality at a time, ranked by demand, business impact, expected answerability, and lifecycle cost.

### How it works technically

Add a hook that records normalized coverage-gap events when the agent encounters a skipped/failed candidate, an unreadable page, or an unsupported modality. Store only fields such as asset team, entry type, format gate, intent category, and outcome—not raw answers or conversation transcripts—so this does not become an accidental answer ledger.

Create a simple score:

`question frequency × operational value × expected parse success ÷ ingest + maintenance cost`

Use `check_document_status` and the ledger to quantify the addressable backlog. Then implement the highest-scoring adapter:

- For ultra-tall TIF/log strips, tile the source at readable resolution, retain page/pixel/depth mapping, embed tiles separately, and let `read_evidence` perform vision on the selected crop while preserving the source page citation.
- For Excel, first make an explicit citation decision: produce a deterministic canonical render with page-to-sheet/cell mapping, or keep the format deferred. Never pretend a workbook had native pages.
- Treat EML/XML/ZIP as separate adapters with independent benchmarks rather than one generic “support everything” parser.

Add an `ingest_policy_version` to the ledger settlement identity. Today an unchanged terminal skip remains settled forever; changing a format from “skip” to “parse” must reopen those bytes even when its ETag is unchanged.

Each adapter gets page-labeled benchmark questions, cost/disk measurements, failure accounting, and a go/no-go gate before full-tranche execution.

### Why it is accretive for Formentera

This steadily reduces the archive’s real blind spots without repeating the mistake selective graph enrichment already avoided: spending heavily on data that does not answer valuable questions. It also gives stakeholders a transparent explanation for prioritization—“these skipped spreadsheets blocked 38 finance questions”—instead of a vague parser roadmap.

The mechanism can choose very different winners by asset team: Excel may dominate financial demand, while depth-aware log tiling may dominate drilling and petrophysics.

### Implementation sketch

1. Instrument normalized coverage-gap telemetry and publish a monthly ranked backlog.
2. Add `ingest_policy_version` and tests proving that newly supported formats reopen unchanged terminal skips.
3. Select one adapter from measured demand; tall-log tiling is the lowest-governance starting point because it preserves the existing page identity.
4. Add at least five gold questions for that modality and measure retrieval, answer accuracy, cost, and storage.
5. Promote only after the adapter clears its benchmark; otherwise retain the honest ledgered skip.

### Rationale for confidence

Confidence is high in the flywheel and deliberately lower about which format should win first. The repository already exposes exact skip reasons, known image limitations, page screenshots, retained parse geometry, and a working benchmark harness. Those facts make prioritization measurable and adapters testable. Demand weighting protects the project from accumulating expensive format support that looks comprehensive but creates little operational value.
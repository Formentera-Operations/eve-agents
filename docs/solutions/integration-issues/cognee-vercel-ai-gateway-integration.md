---
title: "Embedding cognee knowledge-graph memory behind the Vercel AI Gateway: eight integration pitfalls"
date: 2026-07-06
category: integration-issues
module: doc-intel analysts graph memory (cognee integration)
problem_type: integration_issue
component: assistant
symptoms:
  - "Gateway rejects response_format json_object; cognee instructor json_mode fails with opaque OpenAIException - Invalid input"
  - "Prefixed embedding model ids (openai/text-embedding-3-large) break tiktoken tokenizer mapping"
  - "Unset LLM_* or EMBEDDING_* env silently defaults that path to api.openai.com, bypassing the gateway (content egress)"
  - "Cached session-memory completions feed back into CHUNKS searches and poison provenance (no node_set tags)"
  - "Embedded Kuzu single-writer lock held by an idle service blocks the ingest CLI; stale reads after ingest"
root_cause: config_error
resolution_type: config_change
severity: high
tags: [cognee, vercel-ai-gateway, knowledge-graph, embeddings, egress-guard, kuzu, instructor, fastapi]
---

# Embedding cognee 1.2.2 behind the Vercel AI Gateway: eight silent-failure pitfalls

## Problem

We embedded cognee 1.2.2 (its knowledge-graph build + search stack) inside an
existing FastAPI service (`doc-intel/analysts`) and required every model and
embedding call to route through the Vercel AI Gateway — no direct
`api.openai.com` traffic, because the corpus is confidential well-file content
and egress is a compliance boundary, not a preference.

cognee is not designed for that constraint. It routes LLM and embedding traffic
on independent code paths, defaults several behaviors to "reach out to OpenAI /
phone home / cache aggressively," and — the recurring theme — **fails silently**
when a happy-path assumption breaks: a missing ontology file, an unset embedding
endpoint, a cached completion, a wrong storage root. Nothing raised; the graph
just built wrong, or content left the gateway, or provenance quietly evaporated.

Eight distinct pitfalls surfaced during bring-up. All were fixed and verified by
a full 311-document production ingest. Every fix has the same shape: **convert a
silent fallback into a loud failure, and pin the one configuration the gateway
actually accepts.**

## Symptoms

The exact strings, in the order we hit them:

1. `OpenAIException - Invalid input` — raised on *every* cognify extraction call.
2. `KeyError: Could not automatically map openai/text-embedding-3-large to a tokeniser.` — at embedding-engine init, before any embedding call went out.
3. (No error) — with `LLM_*` set but `EMBEDDING_*` unset, embedding traffic silently went to `api.openai.com`. The only "symptom" was gateway usage showing zero embedding calls while the ingest clearly embedded.
4. (No error) — cognee posted usage telemetry to its own endpoint by default.
5. (No error) — a `CHUNKS` search issued after a `GRAPH_COMPLETION` in the same session returned **1 cached item with no `belongs_to_set` tags** instead of the expected **5 real chunks with S3-key tags**. Document-key provenance silently broke.
6. `MigrationError: database migration failed for the global database (global)... it retries automatically on the next call` — on the very first cognify of a fresh store.
7. `RuntimeError: Could not set lock on file ... (Lock is held by PID <n>)` — a CLI ingest failed while the FastAPI service was merely *idle*.
8. (No error) `No valid ontology files found. No owl ontology will be attached` — logged at INFO while the entire graph built **untyped**. Caught only in PR review.

## What Didn't Work

- **Double-prefixing the embedding id.** After the tokeniser `KeyError` on
  `openai/text-embedding-3-large`, the instinct was that the gateway needs the
  provider prefix, so the tokeniser problem must be cosmetic. It is not: the
  gateway accepts *both* the bare and prefixed embedding id over HTTP (verified
  by direct curl), but cognee passes whatever string you configure straight to
  `tiktoken`, which only maps bare OpenAI ids. The prefix has to come off.

- **Prefix-`startswith` egress guard.** The first guard checked
  `endpoint.startswith(GATEWAY_BASE_URL)`. That passes
  `https://ai-gateway.vercel.sh/v1.evil.com` — a lookalike host where the
  gateway string is a prefix but the *host* is attacker-controlled. A prefix
  check on a URL is not a host check.

- **Assuming `RDFLibOntologyResolver` would raise on a missing file.** It does
  not. `RDFLibOntologyResolver(ontology_file="/wrong/path.owl")` constructs
  fine and logs one INFO line. We fed it a path built from a wrong
  `Path(...).parents[N]` and got a fully-built, completely untyped graph with no
  exception anywhere.

- **Trusting an "idle" service to hold no locks.** The reasoning was "the
  service isn't ingesting, so the CLI can grab the Kuzu lock." Wrong — cognee
  lazily opens the store on first use, and once open the process holds the
  single-writer lock for its whole lifetime, idle or not.

## Solution

### The config module (`graph/config.py`) — env before import, guarded

cognee reads env at import/first-use. So one module sets **all** of it and runs
a hard guard, and `runtime.get_cognee()` calls `configure()` *before* the
deferred `import cognee`. The full env block:

```python
defaults = {
    # LLM path — gateway only.
    "LLM_PROVIDER": "custom",
    "LLM_MODEL": llm_model,                 # "openai/anthropic/claude-haiku-4.5"
    "LLM_ENDPOINT": GATEWAY_BASE_URL,       # https://ai-gateway.vercel.sh/v1
    "LLM_API_KEY": key,
    # Embedding path — gateway only (unset silently means api.openai.com).
    "EMBEDDING_PROVIDER": "openai",
    "EMBEDDING_MODEL": embedding_model,     # BARE "text-embedding-3-large"
    "EMBEDDING_ENDPOINT": GATEWAY_BASE_URL,
    "EMBEDDING_API_KEY": key,
    "EMBEDDING_DIMENSIONS": "3072",
    "EMBEDDING_MAX_TOKENS": "8191",
    # gateway rejects response_format json_object (instructor's default
    # json_mode for custom providers); tool_call works (verified live).
    "LLM_INSTRUCTOR_MODE": "tool_call",
    # session-memory caching poisons CHUNKS provenance (see pitfall 5).
    "CACHING": "false",
    # no third egress path.
    "TELEMETRY_DISABLED": "1",
    # embedded single-tenant stores with EXPLICIT roots (else venv-relative).
    "DB_PROVIDER": "sqlite",
    "GRAPH_DATABASE_PROVIDER": "kuzu",
    "VECTOR_DB_PROVIDER": "lancedb",
    "DATA_ROOT_DIRECTORY": str(DATA_ROOT),
    "SYSTEM_ROOT_DIRECTORY": str(SYSTEM_ROOT),
    "ENABLE_BACKEND_ACCESS_CONTROL": "false",   # defaults ON in 1.2.2; shards storage per-user
    "REQUIRE_AUTHENTICATION": "false",
}
for name, value in defaults.items():
    os.environ.setdefault(name, value)   # operator env wins — but still guarded
```

**Pitfall 1 — instructor mode.** `LLM_INSTRUCTOR_MODE=tool_call`. cognee's
instructor default for a `custom` provider is `json_mode`, which sends
`response_format: {"type": "json_object"}`. The gateway rejects that parameter
(confirmed param-level by direct curl against both candidate models).
Function-calling mode is gateway-supported.

**Pitfall 2 — bare embedding id.** `EMBEDDING_MODEL=text-embedding-3-large`, no
`openai/` prefix. The gateway takes either; `tiktoken` (which cognee calls with
the raw configured string) only maps the bare id.

**Pitfall 3 + 4 — the egress guard.** Set both `LLM_*` and `EMBEDDING_*`
explicitly, then refuse to initialize unless both endpoints' **parsed host**
equals the gateway host and telemetry is off:

```python
def _assert_gateway_only() -> None:
    gateway_host = urlparse(GATEWAY_BASE_URL).netloc
    problems = []
    for group in ("LLM", "EMBEDDING"):
        endpoint = os.environ.get(f"{group}_ENDPOINT", "")
        # host equality, NOT prefix: "https://ai-gateway.vercel.sh/v1.evil.com"
        # must not slip past.
        if urlparse(endpoint).netloc != gateway_host:
            problems.append(f"{group}_ENDPOINT is {endpoint!r} — must point at the gateway")
        if not os.environ.get(f"{group}_API_KEY"):
            problems.append(f"{group}_API_KEY is unset")
    if os.environ.get("TELEMETRY_DISABLED") not in ("1", "true", "True"):
        problems.append("TELEMETRY_DISABLED must be set — cognee telemetry is an egress path")
    if problems:
        raise GraphConfigError("Refusing to initialize cognee; content could leave the gateway path: "
                               + "; ".join(problems))
```

This guard has 6 tests, including the lookalike-host case. `TELEMETRY_DISABLED`
(pitfall 4) is folded into the same guard because telemetry is a *third* egress
path — the var name was verified by grepping the installed 1.2.2 source, not
assumed.

**Pitfall 5 — caching off + `model_dump` for tags.** `CACHING=false`. cognee 1.0+
ships session-memory caching on by default, and it returns cached completions to
*later* searches in the same session — a `CHUNKS` search after a
`GRAPH_COMPLETION` got the cached completion (1 item, no tags) instead of the 5
tagged chunks. Separately: cognee search results are pydantic models, so any
code walking `belongs_to_set` tags must `model_dump()` them first — the tags
don't survive attribute access the naive way.

**Pitfall 6 — retry-once on the migration transient.** First-ever cognify can
raise `MigrationError` for the global DB; the error text itself says it retries
on the next call. So catch exactly that and retry once:

```python
try:
    await cognee.cognify(**kwargs)
except Exception as err:
    if "migration" not in str(err).lower():
        raise
    await cognee.cognify(**kwargs)   # self-heals on the second call
```

**Pitfall 7 — service stopped during ingest.** Embedded Kuzu is single-writer
with a **process-held** lock. The operational rule (documented at the top of
`ingest.py` and printed by `main()`): **stop the analysts service during ingest,
restart after** — a long-lived service also won't see post-ingest data without a
reopen. `runtime.release()` exists as the belt to that suspenders (best-effort
handle drop), but the hard rule is service-stopped. This pairs with pitfall 3's
env discipline: because cognee resolves storage paths venv-relative by default,
`config.py` sets `DATA_ROOT_DIRECTORY` / `SYSTEM_ROOT_DIRECTORY` (and
`ENABLE_BACKEND_ACCESS_CONTROL=false`, which defaults ON in 1.2.2 and shards
storage per-user) **before** the first import — an early probe that imported
`RDFLibOntologyResolver` before `configure()` ran saw an empty default-path
store.

**Pitfall 8 — fail-loud ontology guard.** Compute the path correctly
(`parents[6]` here — this module sits one level deeper than its siblings, whose
`parents[5]` idiom does *not* transfer) and check existence before building:

```python
ontology = Path(__file__).resolve().parents[6] / "references" / "ontology" / "welldrive.owl"
if not ontology.exists():
    # RDFLibOntologyResolver silently proceeds without a missing file (verified
    # live) — which would rebuild the graph UNTYPED. Fail loud.
    raise FileNotFoundError(f"ontology not found at {ontology}")
```

## Why This Works

The eight pitfalls collapse into four root causes:

- **Gateway API surface ≠ OpenAI API surface.** The Vercel AI Gateway is
  OpenAI-*compatible*, not OpenAI-identical: it rejects `response_format:
  json_object` (pitfall 1) and it accepts bare embedding ids (pitfall 2). cognee
  assumes the vanilla OpenAI surface. Every claimed difference here was verified
  against the live gateway by direct curl, not inferred.

- **cognee's silent-fallback design philosophy.** When a happy-path assumption
  breaks, cognee's default is to degrade quietly, not raise: unset embedding
  endpoint → OpenAI (3), missing ontology → untyped graph (8), telemetry on by
  default (4), caching on by default (5), storage roots venv-relative by default
  (7), access-control on by default (7). None of these throw. Each is a place
  where "no error" is the *most dangerous* outcome, because it means confidential
  content left the boundary or the graph is subtly wrong.

- **The litellm / instructor / tiktoken layering.** The stack under cognee has
  three independent opinions. instructor picks the structured-output transport
  (json_mode vs tool_call — pitfall 1). tiktoken picks the tokeniser by exact
  string match (pitfall 2). litellm routes the HTTP call. A single configured
  model string flows through all three, and each interprets it differently — the
  gateway-friendly string and the tiktoken-friendly string are not the same
  string, which is why the bare id + explicit `EMBEDDING_DIMENSIONS`/`MAX_TOKENS`
  is load-bearing.

- **Kuzu process locking.** Embedded Kuzu holds a single-writer lock at the OS
  file level, tied to the process, acquired lazily on first store access and
  held for the process lifetime. "The service isn't doing anything" is
  irrelevant — an idle process that once touched the store still owns the lock,
  so two processes (service + CLI) can never both hold it.

## Prevention

The generalizable pattern, for the next time cognee or any similar
"batteries-included, phones-home" library gets embedded behind a hard
constraint:

1. **Fail loud on every silent fallback.** Wherever the library degrades quietly
   on a broken assumption — missing file, unset config, transparent cache — add a
   guard that raises. The ontology `FileNotFoundError` and the egress guard are
   the same move: turn "no error, wrong result" into "loud error, no result."

2. **Env-before-import discipline.** For any library that reads env at import
   time, set *all* of it in one module and import the library only through a
   function that runs that config first. Never let a probe or a test import the
   library ahead of configuration — it will bind to defaults you didn't choose
   (empty default-path store).

3. **Egress guard = host equality + telemetry + cache.** For a gateway-only
   constraint, compare `urlparse(endpoint).netloc` for exact equality (never
   `startswith` on a URL), require every credential group be set, *and* close the
   secondary egress paths (telemetry, and caching where a cache leaks provenance).
   Test the guard with a lookalike host.

4. **Retry-once for known transients.** When a library documents its own
   transient ("retries automatically on the next call"), match that error text
   narrowly and retry once — don't blanket-catch, or you'll mask real failures.

5. **Service-stopped rule for embedded single-writer stores.** Any embedded store
   with a process-held lock (Kuzu, SQLite in some modes, LanceDB writers) means:
   stop the long-lived reader during a batch write, restart after. Don't rely on
   "idle" — provide an explicit `release()` as backup, but make the operational
   rule the primary control and print it at the top of the ingest CLI.

6. **Verify claimed API surfaces against the installed source at unit start.**
   Every "the gateway accepts X" / "cognee's default is Y" here was checked
   against the running gateway (curl) or the installed 1.2.2 source (grep) before
   being relied on — the `TELEMETRY_DISABLED` var name, the instructor default,
   the per-item cognify qualification. Assume nothing about a fast-moving
   dependency; the source is on disk, read it.

## Related Issues

- PR #6 — feat(doc-intel): stage-1 memory (merged; carries all eight fixes and the review threads that caught pitfall 8)
- docs/plans/2026-07-05-001-feat-doc-intel-memory-plan.md — the originating plan (U1 guard, U2 ontology, U3 ingest)
- decisions/2026-07-05-doc-intel-seam.md — why cognee is embedded in the FastAPI analysts service
- benchmark/results/2026-07-06-memory-gates.md — gate record incl. the untyped-graph rebuild addendum
- references/graph-export.md — the provenance (s3key node_set tags) these pitfalls threatened

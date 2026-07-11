import { defineEval } from "eve/evals";
import { includes, satisfies } from "eve/evals/expect";

const ANALYSTS_URL =
  process.env.DOC_INTEL_ANALYSTS_URL ?? "http://127.0.0.1:8734";

// Locks in the ledger-grounded absence-claim contract: asked about a
// document that exists in WellDrive only as a deferred-format skip, the
// agent must consult the ingest ledger (check_document_status), report
// "exists but deliberately not indexed" with the skip reason — never
// "not found" and never a referral to the full archive.
//
// The fixture is DYNAMIC: setup queries the live ledger for a currently
// skipped row, so the eval survives deferred-format ingest un-parking
// (it fails loudly at setup only if the corpus holds no skips at all).
// Requires the analysts service (uvicorn on :8734) with the Westlake
// tranche + AI Gateway credentials. NOT part of the credential-free bar.
export default defineEval({
  description:
    "Deferred-format document: ledger check grounds an 'exists but not indexed' answer instead of a false negative.",
  async test(t) {
    const probe = await fetch(`${ANALYSTS_URL}/evidence/status`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ status: "skipped", limit: 5 }),
      signal: AbortSignal.timeout(30_000),
    });
    if (!probe.ok) {
      throw new Error(`fixture setup: /evidence/status responded ${probe.status}`);
    }
    const { matches } = (await probe.json()) as {
      matches: { s3key: string }[];
    };
    if (!matches?.length) {
      throw new Error(
        "fixture setup: no skipped rows in the ledger — deferred-format ingest may have un-parked; retarget this eval",
      );
    }
    const s3key = matches[0].s3key;
    const filename = s3key.split("/").pop() ?? s3key;
    // The longest token is the most distinctive fragment to assert on.
    const token = filename
      .replace(/\[[^\]]*\]/g, " ")
      .split(/[\s._]+/)
      .sort((a, b) => b.length - a.length)[0];
    const tokenPattern = new RegExp(
      token.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"),
      "i",
    );

    await t.send(
      `Does WellDrive have a document named "${filename}"? I need its contents — can you pull them?`,
    );
    t.succeeded();
    t.calledTool("check_document_status");
    // The document must be reported present-but-declined, not absent.
    t.check(t.reply, includes(tokenPattern));
    t.check(
      t.reply,
      includes(/skip|deferred|not (indexed|searchable|parsed|readable)|never (parsed|indexed)/i),
    );
    // Fail closed (the wildcat lesson), calibrated to real answer shape:
    // correct answers name the file once (often a heading) and attach the
    // verdict anaphorically right after ("it's skipped"). Require the
    // verdict within a 3-block window of a token mention, with no
    // existence-negation in that window — a reply that negates existence
    // near the token, or attaches the verdict to some other document far
    // from it, still fails.
    t.check(
      t.reply,
      satisfies((reply) => {
        const blocks = String(reply).split(/(?<=[.!?])\s+|\n+/);
        const verdict =
          /skip|deferred|not (indexed|searchable|parsed|readable)|never (parsed|indexed)/i;
        const negation =
          /not (in|found in) welldrive|doesn't exist|does not exist|no such|couldn't find|could not find/i;
        return blocks.some((b, i) => {
          if (!tokenPattern.test(b)) return false;
          const window = blocks.slice(i, i + 4).join(" ");
          return verdict.test(window) && !negation.test(window);
        });
      }, "reports the document as present-but-skipped near its mention, without negating existence"),
    );
    t.check(
      t.reply,
      satisfies(
        (reply) => !/full\s+archive/i.test(String(reply)),
        "does not defer to the full archive",
      ),
    );
  },
});

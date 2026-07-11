import { defineEval } from "eve/evals";
import { includes, satisfies } from "eve/evals/expect";
import { z } from "zod";

const ANALYSTS_URL =
  process.env.DOC_INTEL_ANALYSTS_URL ?? "http://127.0.0.1:8734";

const probeSchema = z.object({
  matches: z.array(z.object({ s3key: z.string() })),
});

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
    const { matches } = probeSchema.parse(await probe.json());
    if (!matches.length) {
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
    // The ledger lookup must be driven by the asked document, not merely
    // fired — the call's name_query must be a genuine fragment of the asked
    // key (the model reasonably queries short distinctive tokens like a
    // well code, so "fragment of the key", not "equals the filename").
    t.calledTool("check_document_status", {
      input: {
        name_query: (value) =>
          typeof value === "string" &&
          value.length >= 3 &&
          s3key.toLowerCase().includes(value.toLowerCase()),
      },
    });
    // The document must be reported present-but-declined, not absent.
    t.check(t.reply, includes(tokenPattern));
    t.check(
      t.reply,
      includes(/skip|deferred|not (indexed|searchable|parsed|readable)|never (parsed|indexed)/i),
    );
    // Fail closed (the wildcat lesson), calibrated to real answer shape:
    // correct answers name the file once (often a heading) and attach the
    // verdict anaphorically right after ("it's skipped"). Require, within a
    // 3-block window of a token mention: the skip verdict, an AFFIRMATIVE
    // existence signal, and no negation/hedge — a hedged non-answer
    // ("couldn't confirm, may be deferred") or an existence denial near the
    // token still fails. Negation vocabulary matches the wildcat precedent.
    t.check(
      t.reply,
      satisfies((reply) => {
        const blocks = String(reply).split(/(?<=[.!?])\s+|\n+/);
        const verdict =
          /skip|deferred|not (indexed|searchable|parsed|readable)|never (parsed|indexed)/i;
        const affirmative =
          /exists|is in welldrive|welldrive (has|holds|contains)|found (it|in)|is present|located/i;
        // Hedges and existence denials fail; capability statements the
        // correct answer naturally contains ("can't pull its contents"
        // because the format is deferred) must not.
        const negation =
          /(cannot|can't|could not|couldn't|unable to) (confirm|verify|find|locate|determine|tell)|no evidence|unclear|unverified|not (in|found in) welldrive|doesn't exist|does not exist|no such|is(n't| not) (in|present|available)|no record|(did not|didn't|never) (find|locate)/i;
        return blocks.some((b, i) => {
          if (!tokenPattern.test(b)) return false;
          const window = blocks.slice(i, i + 4).join(" ");
          return (
            verdict.test(window) &&
            affirmative.test(window) &&
            !negation.test(window)
          );
        });
      }, "affirms existence and the skip verdict near the document mention, with no negation or hedge"),
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

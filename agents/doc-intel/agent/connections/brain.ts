import { defineMcpClientConnection } from "eve/connections";

// Formentera company brain — hosted recall-only MCP service (Azure Container
// Apps, bearer auth). Read-only by design: writes stay in the brain's own
// batch-ingest pipeline. See company-brain/docs/plans/
// 2026-07-12-001-feat-mcp-service-deployment-plan.md (U6).
export default defineMcpClientConnection({
  url: "https://ca-fmtr-company-brain-mcp.braveocean-1bff0e24.southcentralus.azurecontainerapps.io/mcp",
  description:
    "Formentera company brain: cross-document answers about Westlake Resources' " +
    "Bull Mountain 31-18 and Wildcat Hollow drilling units (well files and land " +
    "documents). Use recall for narrative/synthesis questions. Not reliable for " +
    "page-precise numeric lookups or anything outside those two units — always " +
    "honor the scope block and disclaimer in each response.",
  auth: {
    getToken: async () => ({ token: process.env.BRAIN_MCP_TOKEN! }),
  },
  tools: { allow: ["recall"] },
});

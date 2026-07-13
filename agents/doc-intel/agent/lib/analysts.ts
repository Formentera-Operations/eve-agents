/**
 * Shared seam config for tools that call the analysts service.
 *
 * The bearer token (DOC_INTEL_ANALYSTS_TOKEN) is read at call time so hosted
 * deployments can inject it via env; when unset, no authorization header is
 * sent (local dev against an open service).
 */

export const ANALYSTS_URL =
  process.env.DOC_INTEL_ANALYSTS_URL ?? "http://127.0.0.1:8734";

export function analystHeaders(): Record<string, string> {
  const token = process.env.DOC_INTEL_ANALYSTS_TOKEN;
  return {
    "content-type": "application/json",
    ...(token ? { authorization: `Bearer ${token}` } : {}),
  };
}

/**
 * Error message for a non-OK response from the analysts service. 401 means
 * the bearer token is wrong — an operator problem, not a retriable one — so
 * it gets an actionable message; every other status keeps the generic text.
 */
export function analystError(service: string, status: number): string {
  if (status === 401) {
    return `${service} rejected the request (401 unauthorized). DOC_INTEL_ANALYSTS_TOKEN is missing, stale, or does not match the service token — an operator must fix the credential. Do not retry with different arguments.`;
  }
  return `${service} responded ${status}.`;
}

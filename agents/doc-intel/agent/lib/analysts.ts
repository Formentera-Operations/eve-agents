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

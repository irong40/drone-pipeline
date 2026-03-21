/**
 * HMAC-SHA256 signature verification for WhatsApp webhooks.
 *
 * Uses Web Crypto API (Deno/browser compatible, NOT Node.js crypto).
 * Implements timing-safe comparison to prevent timing attacks.
 */

/**
 * Verify an HMAC-SHA256 signature from a webhook request.
 *
 * @param body - Raw request body as string
 * @param signatureHeader - The "sha256=..." header value
 * @param secret - The app secret used to compute the HMAC
 * @returns true if the signature is valid
 */
export async function verifyHmacSignature(
  body: string,
  signatureHeader: string,
  secret: string,
): Promise<boolean> {
  if (!signatureHeader || !signatureHeader.startsWith("sha256=")) {
    return false;
  }

  const providedHex = signatureHeader.slice("sha256=".length);

  const encoder = new TextEncoder();
  const key = await crypto.subtle.importKey(
    "raw",
    encoder.encode(secret),
    { name: "HMAC", hash: "SHA-256" },
    false,
    ["sign"],
  );

  const signature = await crypto.subtle.sign(
    "HMAC",
    key,
    encoder.encode(body),
  );

  const computedHex = Array.from(new Uint8Array(signature))
    .map((b) => b.toString(16).padStart(2, "0"))
    .join("");

  // Timing-safe comparison: always compare all bytes
  return timingSafeEqual(computedHex, providedHex);
}

/**
 * Constant-time string comparison to prevent timing attacks.
 */
function timingSafeEqual(a: string, b: string): boolean {
  if (a.length !== b.length) {
    return false;
  }
  let result = 0;
  for (let i = 0; i < a.length; i++) {
    result |= a.charCodeAt(i) ^ b.charCodeAt(i);
  }
  return result === 0;
}

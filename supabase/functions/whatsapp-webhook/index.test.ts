/**
 * Tests for WhatsApp webhook Edge Function.
 *
 * Covers: HMAC verification, GET webhook verification,
 * POST with valid/invalid signatures, client lookup.
 */

import {
  assertEquals,
  assertExists,
} from "https://deno.land/std@0.224.0/assert/mod.ts";

// ── HMAC verification tests ────────────────────────────────────────

import { verifyHmacSignature } from "../_shared/hmac.ts";

const TEST_SECRET = "test_app_secret_123";

async function computeHmac(body: string, secret: string): Promise<string> {
  const encoder = new TextEncoder();
  const key = await crypto.subtle.importKey(
    "raw",
    encoder.encode(secret),
    { name: "HMAC", hash: "SHA-256" },
    false,
    ["sign"],
  );
  const sig = await crypto.subtle.sign("HMAC", key, encoder.encode(body));
  const hex = Array.from(new Uint8Array(sig))
    .map((b) => b.toString(16).padStart(2, "0"))
    .join("");
  return `sha256=${hex}`;
}

Deno.test("verifyHmacSignature returns true for valid signature", async () => {
  const body = '{"test":"payload"}';
  const signature = await computeHmac(body, TEST_SECRET);
  const result = await verifyHmacSignature(body, signature, TEST_SECRET);
  assertEquals(result, true);
});

Deno.test("verifyHmacSignature returns false for tampered body", async () => {
  const body = '{"test":"payload"}';
  const signature = await computeHmac(body, TEST_SECRET);
  const result = await verifyHmacSignature(
    '{"test":"tampered"}',
    signature,
    TEST_SECRET,
  );
  assertEquals(result, false);
});

Deno.test("verifyHmacSignature returns false for wrong secret", async () => {
  const body = '{"test":"payload"}';
  const signature = await computeHmac(body, "wrong_secret");
  const result = await verifyHmacSignature(body, signature, TEST_SECRET);
  assertEquals(result, false);
});

// ── Webhook handler tests ──────────────────────────────────────────

// Mock Supabase client for testing
const mockClients: Record<string, { id: string; phone: string; name: string | null }> = {};
let activityLogs: Array<{ event_type: string; payload: unknown }> = [];

// We'll test the handler via the exported handler function
import { handleRequest } from "./index.ts";

// Set env vars for tests
Deno.env.set("WHATSAPP_VERIFY_TOKEN", "test_verify_token");
Deno.env.set("WHATSAPP_APP_SECRET", TEST_SECRET);
Deno.env.set("SUPABASE_URL", "http://localhost:54321");
Deno.env.set("SUPABASE_SERVICE_ROLE_KEY", "test-service-role-key");

Deno.test("GET with correct verify_token returns hub.challenge", async () => {
  const url = new URL(
    "http://localhost/whatsapp-webhook?hub.mode=subscribe&hub.verify_token=test_verify_token&hub.challenge=challenge_abc",
  );
  const req = new Request(url.toString(), { method: "GET" });
  const res = await handleRequest(req);
  assertEquals(res.status, 200);
  const text = await res.text();
  assertEquals(text, "challenge_abc");
});

Deno.test("GET with wrong verify_token returns 403", async () => {
  const url = new URL(
    "http://localhost/whatsapp-webhook?hub.mode=subscribe&hub.verify_token=wrong_token&hub.challenge=challenge_abc",
  );
  const req = new Request(url.toString(), { method: "GET" });
  const res = await handleRequest(req);
  assertEquals(res.status, 403);
});

Deno.test("POST with invalid X-Hub-Signature-256 returns 401", async () => {
  const body = '{"object":"whatsapp_business_account","entry":[]}';
  const req = new Request("http://localhost/whatsapp-webhook", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "X-Hub-Signature-256": "sha256=invalid",
    },
    body,
  });
  const res = await handleRequest(req);
  assertEquals(res.status, 401);
  const json = await res.json();
  assertEquals(json.error, "Invalid signature");
});

function buildWebhookPayload(
  phone: string,
  name: string,
  text: string,
): string {
  return JSON.stringify({
    object: "whatsapp_business_account",
    entry: [
      {
        id: "123456",
        changes: [
          {
            value: {
              messaging_product: "whatsapp",
              metadata: {
                display_phone_number: "15551234567",
                phone_number_id: "phone_id_1",
              },
              contacts: [{ profile: { name }, wa_id: phone }],
              messages: [
                {
                  from: phone,
                  id: "wamid.abc123",
                  timestamp: "1700000000",
                  type: "text",
                  text: { body: text },
                },
              ],
            },
            field: "messages",
          },
        ],
      },
    ],
  });
}

Deno.test("POST with valid signature and new phone returns 200 with clientId", async () => {
  const body = buildWebhookPayload("15559990001", "New User", "Hello");
  const signature = await computeHmac(body, TEST_SECRET);
  const req = new Request("http://localhost/whatsapp-webhook", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "X-Hub-Signature-256": signature,
    },
    body,
  });
  const res = await handleRequest(req);
  assertEquals(res.status, 200);
  const json = await res.json();
  assertEquals(json.status, "received");
  assertExists(json.clientId);
});

Deno.test("POST with valid signature and known phone returns existing client", async () => {
  // Send same phone again - should match existing
  const body = buildWebhookPayload("15559990001", "New User", "Hello again");
  const signature = await computeHmac(body, TEST_SECRET);
  const req = new Request("http://localhost/whatsapp-webhook", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "X-Hub-Signature-256": signature,
    },
    body,
  });
  const res = await handleRequest(req);
  assertEquals(res.status, 200);
  const json = await res.json();
  assertEquals(json.status, "received");
  assertExists(json.clientId);
});

Deno.test("POST with valid signature extracts WhatsAppMessage correctly", async () => {
  const body = buildWebhookPayload(
    "15559990002",
    "Test Contact",
    "Extract test",
  );
  const signature = await computeHmac(body, TEST_SECRET);
  const req = new Request("http://localhost/whatsapp-webhook", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "X-Hub-Signature-256": signature,
    },
    body,
  });
  const res = await handleRequest(req);
  assertEquals(res.status, 200);
  const json = await res.json();
  assertEquals(json.status, "received");
  // The message was extracted and processed (client created/found)
  assertExists(json.clientId);
  // Verify message details are in response
  assertExists(json.messages);
  assertEquals(json.messages.length, 1);
  assertEquals(json.messages[0].phone, "15559990002");
  assertEquals(json.messages[0].textBody, "Extract test");
  assertEquals(json.messages[0].displayName, "Test Contact");
  assertEquals(json.messages[0].type, "text");
});

Deno.test("POST with valid signature but no messages returns 200", async () => {
  // Status update payload (no messages)
  const body = JSON.stringify({
    object: "whatsapp_business_account",
    entry: [
      {
        id: "123456",
        changes: [
          {
            value: {
              messaging_product: "whatsapp",
              metadata: {
                display_phone_number: "15551234567",
                phone_number_id: "phone_id_1",
              },
              statuses: [{ id: "wamid.status1", status: "delivered" }],
            },
            field: "messages",
          },
        ],
      },
    ],
  });
  const signature = await computeHmac(body, TEST_SECRET);
  const req = new Request("http://localhost/whatsapp-webhook", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "X-Hub-Signature-256": signature,
    },
    body,
  });
  const res = await handleRequest(req);
  assertEquals(res.status, 200);
  const json = await res.json();
  assertEquals(json.status, "no_messages");
});

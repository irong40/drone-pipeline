/**
 * WhatsApp Webhook Edge Function.
 *
 * Handles:
 * - GET: Webhook verification (hub.challenge handshake)
 * - POST: Message ingestion with HMAC-SHA256 verification
 *
 * After verification, messages are parsed, clients are identified
 * (find-or-create), and a 200 response is returned.
 * Routing chain (Plan 02) will add priority-based message routing.
 */

import { verifyHmacSignature } from "../_shared/hmac.ts";
import { findOrCreateClient } from "../_shared/client-lookup.ts";
import type {
  WhatsAppMessage,
  WhatsAppWebhookPayload,
} from "../_shared/types.ts";

// deno-lint-ignore no-explicit-any
type ClientLookupFn = (phone: string, displayName?: string, db?: any) => Promise<any>;

export interface HandlerDeps {
  clientLookup: ClientLookupFn;
  // deno-lint-ignore no-explicit-any
  logActivity: (eventType: string, payload: Record<string, unknown>) => Promise<any>;
}

const defaultDeps: HandlerDeps = {
  clientLookup: findOrCreateClient,
  logActivity: async (eventType, payload) => {
    const { supabaseAdmin } = await import("../_shared/supabase-client.ts");
    await supabaseAdmin.from("activity_log").insert({
      event_type: eventType,
      payload,
    });
  },
};

/**
 * Handle an incoming webhook request.
 * Exported for testing -- Deno.serve calls this in production.
 */
export async function handleRequest(
  req: Request,
  deps: HandlerDeps = defaultDeps,
): Promise<Response> {
  const url = new URL(req.url);

  // ── GET: Webhook verification ──────────────────────────────────
  if (req.method === "GET") {
    const mode = url.searchParams.get("hub.mode");
    const token = url.searchParams.get("hub.verify_token");
    const challenge = url.searchParams.get("hub.challenge");
    const verifyToken = Deno.env.get("WHATSAPP_VERIFY_TOKEN");

    if (mode === "subscribe" && token === verifyToken) {
      return new Response(challenge ?? "", { status: 200 });
    }
    return new Response("Forbidden", { status: 403 });
  }

  // ── POST: Message ingestion ────────────────────────────────────
  if (req.method === "POST") {
    const body = await req.text();

    // Verify HMAC signature
    const signatureHeader = req.headers.get("X-Hub-Signature-256") ?? "";
    const appSecret = Deno.env.get("WHATSAPP_APP_SECRET") ?? "";

    const isValid = await verifyHmacSignature(body, signatureHeader, appSecret);
    if (!isValid) {
      return new Response(
        JSON.stringify({ error: "Invalid signature" }),
        {
          status: 401,
          headers: { "Content-Type": "application/json" },
        },
      );
    }

    // Parse payload
    const payload: WhatsAppWebhookPayload = JSON.parse(body);
    const entry = payload.entry?.[0];
    const changes = entry?.changes?.[0];
    const value = changes?.value;
    const rawMessages = value?.messages;

    if (!rawMessages || rawMessages.length === 0) {
      return new Response(
        JSON.stringify({ status: "no_messages" }),
        {
          status: 200,
          headers: { "Content-Type": "application/json" },
        },
      );
    }

    // Extract contacts map for display names
    const contacts = value?.contacts ?? [];
    const contactMap = new Map(
      contacts.map((c) => [c.wa_id, c.profile.name]),
    );

    // Process each message
    const messages: WhatsAppMessage[] = [];
    let lastClientId: string | undefined;

    for (const raw of rawMessages) {
      const displayName = contactMap.get(raw.from) ?? "Unknown";

      // Extract media info
      const mediaObj = raw.image ?? raw.video ?? raw.audio ?? raw.document;
      const mediaId = mediaObj?.id ?? null;
      const mediaType = mediaObj?.mime_type ?? null;

      const extracted: WhatsAppMessage = {
        phone: raw.from,
        displayName,
        timestamp: parseInt(raw.timestamp, 10),
        type: raw.type,
        textBody: raw.text?.body ?? null,
        mediaId,
        mediaType,
      };
      messages.push(extracted);

      // Identify client
      const client = await deps.clientLookup(raw.from, displayName);
      lastClientId = client.id;
    }

    // Log webhook receipt
    await deps.logActivity("webhook_received", {
      messageCount: messages.length,
      phones: messages.map((m) => m.phone),
    });

    return new Response(
      JSON.stringify({
        status: "received",
        clientId: lastClientId,
        messages,
      }),
      {
        status: 200,
        headers: { "Content-Type": "application/json" },
      },
    );
  }

  // Other methods not supported
  return new Response("Method not allowed", { status: 405 });
}

// ── Start server (production only) ───────────────────────────────
// Skip auto-start when imported by test runner
const isTest = Deno.env.get("DENO_TESTING") === "true" ||
  import.meta.url !== Deno.mainModule;

if (!isTest) {
  Deno.serve((req: Request) => handleRequest(req));
}

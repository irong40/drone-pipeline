/**
 * Shared type definitions for WhatsApp webhook processing.
 *
 * These types are used across all Edge Functions in the input-routing phase.
 */

// ── WhatsApp Webhook Payload (Meta's format) ────────────────────────

export interface WhatsAppMediaObject {
  id: string;
  mime_type: string;
}

export interface WhatsAppTextObject {
  body: string;
}

export interface WhatsAppRawMessage {
  from: string;
  id: string;
  timestamp: string;
  type: "text" | "image" | "video" | "audio" | "document";
  text?: WhatsAppTextObject;
  image?: WhatsAppMediaObject;
  video?: WhatsAppMediaObject;
  audio?: WhatsAppMediaObject;
  document?: WhatsAppMediaObject;
}

export interface WhatsAppContact {
  profile: {
    name: string;
  };
  wa_id: string;
}

export interface WhatsAppValue {
  messaging_product: string;
  metadata: {
    display_phone_number: string;
    phone_number_id: string;
  };
  contacts?: WhatsAppContact[];
  messages?: WhatsAppRawMessage[];
  statuses?: unknown[];
}

export interface WhatsAppChange {
  value: WhatsAppValue;
  field: string;
}

export interface WhatsAppEntry {
  id: string;
  changes: WhatsAppChange[];
}

export interface WhatsAppWebhookPayload {
  object: string;
  entry: WhatsAppEntry[];
}

// ── Extracted message (normalized) ──────────────────────────────────

export interface WhatsAppMessage {
  phone: string;
  displayName: string;
  timestamp: number;
  type: string;
  textBody: string | null;
  mediaId: string | null;
  mediaType: string | null;
}

// ── Database models ─────────────────────────────────────────────────

export interface Client {
  id: string;
  phone: string;
  name: string | null;
  manual_mode: boolean;
  opted_out: boolean;
  opted_out_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface MessageRecord {
  id: string;
  conversation_id: string;
  role: string;
  content: string;
  handler: string | null;
  has_media: boolean;
  media_url: string | null;
  created_at: string;
}

// ── Routing ─────────────────────────────────────────────────────────

export interface RouteResult {
  handler: string;
  shouldRespond: boolean;
  responseText?: string;
  forwardTo?: string;
}

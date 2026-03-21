/**
 * Client lookup: find-or-create by phone number.
 *
 * Queries the clients table. If the phone exists, returns the existing
 * record. If not, inserts a new client and logs the event.
 */

import type { Client } from "./types.ts";
import { supabaseAdmin } from "./supabase-client.ts";

// deno-lint-ignore no-explicit-any
type SupabaseClient = any;

/**
 * Find an existing client by phone number, or create a new one.
 *
 * @param phone - The client's phone number (WhatsApp sender)
 * @param displayName - Optional display name from WhatsApp contact
 * @param db - Optional Supabase client (for testing)
 * @returns The client record
 */
export async function findOrCreateClient(
  phone: string,
  displayName?: string,
  db: SupabaseClient = supabaseAdmin,
): Promise<Client> {
  // Try to find existing client
  const { data: existing, error: findError } = await db
    .from("clients")
    .select("*")
    .eq("phone", phone)
    .maybeSingle();

  if (findError) {
    throw new Error(`Client lookup failed: ${findError.message}`);
  }

  if (existing) {
    // Log identification
    await db.from("activity_log").insert({
      event_type: "client_identified",
      payload: { phone },
    });
    return existing as Client;
  }

  // Create new client
  const { data: newClient, error: createError } = await db
    .from("clients")
    .insert({ phone, name: displayName ?? null })
    .select()
    .single();

  if (createError) {
    throw new Error(`Client creation failed: ${createError.message}`);
  }

  // Log creation
  await db.from("activity_log").insert({
    event_type: "client_created",
    payload: { phone },
  });

  return newClient as Client;
}

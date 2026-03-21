/**
 * Supabase admin client for Edge Functions.
 *
 * Uses service_role key for full table access (bypasses RLS).
 * All Edge Functions share this single client instance.
 *
 * Client is lazily initialized to allow test env vars to be set
 * before first access.
 */

import { createClient } from "https://esm.sh/@supabase/supabase-js@2";

// deno-lint-ignore no-explicit-any
type SupabaseClient = any;

let _client: SupabaseClient | null = null;

/**
 * Get the shared Supabase admin client (lazy singleton).
 */
function getClient(): SupabaseClient {
  if (!_client) {
    const supabaseUrl = Deno.env.get("SUPABASE_URL");
    const supabaseServiceRoleKey = Deno.env.get("SUPABASE_SERVICE_ROLE_KEY");

    if (!supabaseUrl || !supabaseServiceRoleKey) {
      throw new Error(
        "Missing SUPABASE_URL or SUPABASE_SERVICE_ROLE_KEY environment variables",
      );
    }

    _client = createClient(supabaseUrl, supabaseServiceRoleKey, {
      auth: {
        autoRefreshToken: false,
        persistSession: false,
      },
    });
  }
  return _client;
}

/**
 * Supabase admin client proxy. Accesses are forwarded to the
 * lazily-initialized real client.
 */
export const supabaseAdmin: SupabaseClient = new Proxy(
  {},
  {
    get(_target, prop) {
      return getClient()[prop];
    },
  },
);

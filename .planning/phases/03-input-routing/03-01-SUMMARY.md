---
phase: 03-input-routing
plan: 01
subsystem: api
tags: [whatsapp, hmac, webhook, supabase, deno, edge-functions]

# Dependency graph
requires: []
provides:
  - WhatsApp webhook Edge Function (GET verification + POST ingestion)
  - HMAC-SHA256 signature verification (Web Crypto API)
  - Client find-or-create by phone number
  - Shared type definitions for WhatsApp payload, Client, Message, RouteResult
  - Supabase admin client (lazy-init singleton)
affects: [03-02-PLAN, 03-03-PLAN]

# Tech tracking
tech-stack:
  added: ["@supabase/supabase-js@2 (esm.sh)", "Deno.serve", "Web Crypto API"]
  patterns: ["dependency injection for testability", "lazy Proxy for Supabase client", "HMAC timing-safe comparison"]

key-files:
  created:
    - supabase/functions/_shared/types.ts
    - supabase/functions/_shared/supabase-client.ts
    - supabase/functions/_shared/hmac.ts
    - supabase/functions/_shared/client-lookup.ts
    - supabase/functions/whatsapp-webhook/index.ts
    - supabase/functions/whatsapp-webhook/index.test.ts
  modified: []

key-decisions:
  - "Used Web Crypto API (not Node.js crypto) for HMAC -- Deno Edge Function compatible"
  - "Lazy-init Proxy pattern for Supabase client to support test env var injection"
  - "Dependency injection (HandlerDeps) on handleRequest for mockable client lookup and activity logging"

patterns-established:
  - "Edge Function structure: export handleRequest for testing, Deno.serve wrapper for production"
  - "Shared types in _shared/types.ts imported by all functions"
  - "Activity logging pattern: insert to activity_log with event_type and payload"

requirements-completed: [INPT-01, INPT-02, INPT-03]

# Metrics
duration: 4min
completed: 2026-03-21
---

# Phase 3 Plan 01: Webhook Endpoint Summary

**WhatsApp webhook with HMAC-SHA256 verification, client find-or-create, and message extraction using Deno Edge Functions**

## Performance

- **Duration:** 4 min
- **Started:** 2026-03-21T21:39:42Z
- **Completed:** 2026-03-21T21:43:40Z
- **Tasks:** 2
- **Files created:** 6

## Accomplishments
- WhatsApp webhook GET verification handshake (hub.challenge)
- HMAC-SHA256 POST signature verification with timing-safe comparison
- Client identification: find-or-create by phone number with activity logging
- Full WhatsApp message extraction from Meta's nested payload format
- 10 passing tests covering all success criteria

## Task Commits

Each task was committed atomically:

1. **Task 1: Shared types and Supabase client** - `3b61fb1` (feat)
2. **Task 2 RED: Failing tests** - `ff2c9c4` (test)
3. **Task 2 GREEN: Implementation** - `2938d48` (feat)

## Files Created/Modified
- `supabase/functions/_shared/types.ts` - WhatsAppWebhookPayload, WhatsAppMessage, Client, MessageRecord, RouteResult
- `supabase/functions/_shared/supabase-client.ts` - Lazy-init Supabase admin client via Proxy
- `supabase/functions/_shared/hmac.ts` - HMAC-SHA256 verification with Web Crypto API
- `supabase/functions/_shared/client-lookup.ts` - Find-or-create client by phone with activity logging
- `supabase/functions/whatsapp-webhook/index.ts` - Edge Function handling GET verify + POST ingestion
- `supabase/functions/whatsapp-webhook/index.test.ts` - 10 test cases (3 HMAC, 2 GET, 5 POST)

## Decisions Made
- Used Web Crypto API instead of Node.js crypto for Deno Edge Function compatibility
- Implemented lazy-init Proxy pattern for Supabase client to support test env var injection without eager module-level initialization
- Added dependency injection (HandlerDeps interface) to handleRequest for fully mockable tests without DB

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Made Supabase client lazy-initialized**
- **Found during:** Task 2 GREEN (running tests)
- **Issue:** supabase-client.ts threw at import time before test env vars were set
- **Fix:** Changed from eager init to lazy Proxy pattern -- client created on first property access
- **Files modified:** supabase/functions/_shared/supabase-client.ts
- **Verification:** All 10 tests pass, deno check passes
- **Committed in:** 2938d48 (Task 2 GREEN commit)

---

**Total deviations:** 1 auto-fixed (1 blocking)
**Impact on plan:** Essential for testability. No scope creep.

## Issues Encountered
None beyond the auto-fixed lazy init issue.

## User Setup Required
None - no external service configuration required. Environment variables (WHATSAPP_VERIFY_TOKEN, WHATSAPP_APP_SECRET, SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY) must be set when deploying to Supabase Edge Functions.

## Next Phase Readiness
- Webhook endpoint ready for Plan 02 (priority routing chain)
- findOrCreateClient and WhatsAppMessage extraction available for routing logic
- RouteResult type defined for routing chain output

---
*Phase: 03-input-routing*
*Completed: 2026-03-21*

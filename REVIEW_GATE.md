# Sentinel Vegetation Pipeline — Review Gate Webhook Contract

## Overview

The review gate is the single human touchpoint in Path E (vegetation analysis). After E4
(vegetation_report.py) generates the draft PDF and maps, n8n pauses at a webhook wait node.
The operator reviews the PDF, then posts decisions back to resume processing.

This document defines the webhook contract so the Trestle admin UI can implement the correct
POST body when the admin interface is built.

---

## Webhook Endpoint

**Method:** POST
**URL:** `/sentinel-vegetation-resume` (n8n webhook wait node URL)
**Content-Type:** `application/json`

---

## Request Body

```json
{
    "mission_id": "uuid",
    "decisions": [
        {"detection_index": 0, "action": "approve"},
        {"detection_index": 5, "action": "exclude", "reason": "false positive — utility pole shadow"},
        {"detection_index": 12, "action": "flag_arborist", "notes": "possible fungal disease on trunk"}
    ]
}
```

### Fields

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `mission_id` | UUID string | Yes | Supabase `drone_jobs.id` for the mission being reviewed |
| `decisions` | Array | Yes | Per-detection review decisions. Omit a detection to implicitly approve it. |

### Decision Object Fields

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `detection_index` | Integer | Yes | Index of the canopy detection (`vegetation_detections.detection_index`) |
| `action` | String | Yes | One of: `approve`, `exclude`, `flag_arborist` |
| `reason` | String | No | Human-readable reason (used for `exclude` actions, stored in notes) |
| `notes` | String | No | Additional context (used for `flag_arborist` actions) |

---

## Actions

### `approve`
Keep the detection in the regenerated report. This is the **default** for any detection
not listed in the `decisions` array — omitting a detection implicitly approves it.

- Supabase: `review_status` → `approved`
- Report: detection included with no special marker

### `exclude`
Remove the detection from the regenerated report entirely. Typically used for false
positives (e.g., utility poles, shrubs, fence posts detected as trees).

- Supabase: `review_status` → `excluded`
- Report: detection omitted from PDF, maps, and delivery GeoJSON
- Reason string stored in `vegetation_detections.review_notes`

### `flag_arborist`
Keep the detection in the report but highlight it with an "arborist recommended" badge.
Typically used for trees showing disease, structural damage, or unusual growth.

- Supabase: `review_status` → `flagged`
- Report: detection included with visual callout and recommendation text
- Notes string stored in `vegetation_detections.review_notes`

---

## Post-Decision Processing (n8n Flow)

After the webhook fires and decisions are processed:

1. **Decision writer node** iterates `decisions` array, writes `review_status` and `review_notes`
   to `vegetation_detections` rows matching `mission_id` + `detection_index`
2. **Re-run E4** — n8n calls `vegetation_report.py` again with `--mission-id {uuid}`. The script
   queries `vegetation_detections WHERE review_status != 'excluded'`, regenerating PDF/maps/GeoJSON
   with only approved and flagged detections
3. **Delivery packaging** — n8n calls `delivery_packaging.py --include-vegetation` to build the
   client ZIP with the final vegetation subfolder

---

## Minimal "Approve All" POST

To approve all detections without reviewing individually, POST with an empty decisions array:

```json
{
    "mission_id": "uuid",
    "decisions": []
}
```

---

## Example: Mixed Review

Operator reviews PDF, finds 2 false positives and 1 diseased tree:

```json
{
    "mission_id": "3f8a2c1e-4b7d-4f9a-8e2c-1a3b5d7f9e2c",
    "decisions": [
        {"detection_index": 3,  "action": "exclude", "reason": "utility pole"},
        {"detection_index": 17, "action": "exclude", "reason": "fence post shadow"},
        {"detection_index": 42, "action": "flag_arborist", "notes": "yellowing foliage consistent with chlorosis"}
    ]
}
```

All other detections (0-2, 4-16, 18-41, 43+) are implicitly approved.

---

## Supabase Schema Reference

The `vegetation_detections` table stores per-canopy review state:

```sql
-- Columns relevant to review gate
detection_index  INTEGER NOT NULL    -- matches decisions[].detection_index
review_status    TEXT                -- null | 'approved' | 'excluded' | 'flagged'
review_notes     TEXT                -- reason/notes from reviewer
```

---

## Admin UI Integration Notes

The review UI should:

1. Display the draft PDF for the given `mission_id` (stored path in `vegetation_analysis_summary`)
2. Show a list of all detections with their species, health status, and a thumbnail crop (centroid)
3. Default all detections to "approve" (green checkmark)
4. Allow per-detection override to "exclude" (red X + reason field) or "flag arborist" (orange flag + notes)
5. On submit, POST the decisions array containing only non-approve overrides to the n8n webhook URL

**Webhook URL storage:** The n8n webhook resume URL is returned by the n8n workflow when the
wait node activates. Store it in `drone_jobs.vegetation_review_webhook_url` (or equivalent)
so the admin UI can retrieve it when opening the review screen.

---

## Out of Scope (Pipeline)

The webhook handler itself is n8n's built-in webhook wait node — no custom server-side code
needed in the pipeline. The pipeline's role is:

- E4 (vegetation_report.py): generate draft output, write paths to Supabase, trigger n8n step completion
- n8n: pause at wait node, surface review URL to admin, resume on POST
- delivery_packaging.py: package the final vegetation outputs after E4 regeneration

Admin UI implementation is part of the Trestle project (out of scope for drone-pipeline).

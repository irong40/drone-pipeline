/**
 * Package Router Payload Normalizer — n8n Code Node
 *
 * Normalizes both folder_watcher and ingest_sorter webhook payloads
 * into a common format before the Package Router Switch node routes
 * them to the appropriate sub-workflow.
 *
 * Input: items[0].json from either folder_watcher or ingest_sorter webhook
 * Output: Normalized payload with consistent keys for routing
 *
 * Paste this into an n8n Code node in the Package Router workflow,
 * positioned between the webhook trigger and the Switch node.
 */

const input = items[0].json;

// Detect source based on payload shape
const hasIngestSorterFields = input.mission_id && !input.folder_name;
const hasFolderWatcherFields = input.folder_name && !input.mission_id;

let normalized;

if (hasIngestSorterFields) {
  // --- ingest_sorter payload: pass through with metadata ---
  normalized = {
    mission_id: input.mission_id,
    mission_number: input.mission_number,
    package_type: input.package_type,
    photo_count: input.photo_count || 0,
    video_count: input.video_count || 0,
    has_ppk_data: input.has_ppk_data || false,
    source: "ingest_sorter",
    needs_mission_lookup: false,
    is_fallback: false,
    folder_path: input.sorted_folder || input.folder_path || "",
  };
} else if (hasFolderWatcherFields) {
  // --- folder_watcher payload: parse folder name for package_type ---
  const folderName = input.folder_name;
  const regex = /^SAI_M(\d{4})_(.+?)_(\d{8})$/;
  const match = folderName.match(regex);

  let missionNumber = input.mission_number || 0;
  let packageType = "unknown";

  if (match) {
    missionNumber = parseInt(match[1], 10);
    packageType = match[2];
  }

  normalized = {
    mission_id: null,
    mission_number: missionNumber,
    package_type: packageType,
    photo_count: input.photo_count || 0,
    video_count: input.video_count || 0,
    has_ppk_data: input.has_ppk_data || false,
    source: "folder_watcher",
    needs_mission_lookup: true,
    is_fallback: true,
    folder_path: input.folder_path || "",
  };
} else {
  // --- Unknown payload shape: pass through with unknown markers ---
  normalized = {
    mission_id: input.mission_id || null,
    mission_number: input.mission_number || 0,
    package_type: input.package_type || "unknown",
    photo_count: input.photo_count || 0,
    video_count: input.video_count || 0,
    has_ppk_data: input.has_ppk_data || false,
    source: "unknown",
    needs_mission_lookup: !input.mission_id,
    is_fallback: false,
    folder_path: input.folder_path || "",
  };
}

return [{ json: normalized }];

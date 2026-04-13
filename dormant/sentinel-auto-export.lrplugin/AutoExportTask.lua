--[[
    Sentinel Auto Export — Full Pipeline Watcher

    Handles EVERYTHING — no LR Auto Import needed:
    1. Polls LR_AutoImport/ for new mission subfolders
    2. Imports photos into the LR catalog programmatically
    3. XMP sidecars are already written by photo_edit.py (presets auto-applied on import)
    4. Auto-exports edited photos to LR_Export/{mission_id}/

    Start from: Library > Plug-in Extras > Start Auto Export Watcher
]]

local LrTasks         = import "LrTasks"
local LrApplication   = import "LrApplication"
local LrExportSession = import "LrExportSession"
local LrLogger        = import "LrLogger"
local LrPrefs         = import "LrPrefs"
local LrDialogs       = import "LrDialogs"
local LrFileUtils     = import "LrFileUtils"
local LrPathUtils     = import "LrPathUtils"

local logger = LrLogger("SentinelAutoExport")
logger:enable("logfile")

local prefs = LrPrefs.prefsForPlugin()

-- Track which missions we've already processed
local processedMissions = {}


-- Scan LR_AutoImport for mission subfolders containing photos
local function scanForNewMissions(importDir)
    local newMissions = {}

    if not LrFileUtils.exists(importDir) then
        return newMissions
    end

    for entry in LrFileUtils.directoryEntries(importDir) do
        local fullPath = LrPathUtils.child(importDir, entry)
        if LrFileUtils.exists(fullPath) == "directory" then
            local missionId = entry
            if not processedMissions[missionId] then
                -- Check if folder has photos
                local photoFiles = {}
                for file in LrFileUtils.directoryEntries(fullPath) do
                    local ext = string.lower(LrPathUtils.extension(file) or "")
                    if ext == "dng" or ext == "jpg" or ext == "jpeg"
                       or ext == "tif" or ext == "tiff" or ext == "arw"
                       or ext == "cr2" or ext == "cr3" or ext == "nef" then
                        table.insert(photoFiles, LrPathUtils.child(fullPath, file))
                    end
                end
                if #photoFiles > 0 then
                    newMissions[missionId] = {
                        path = fullPath,
                        photos = photoFiles,
                    }
                end
            end
        end
    end

    return newMissions
end


-- Import photos into the LR catalog
-- XMP sidecars written by photo_edit.py will be read automatically
local function importPhotos(catalog, missionId, missionData)
    local photoPaths = missionData.photos
    local folderPath = missionData.path

    logger:info("Importing " .. #photoPaths .. " photos for mission " .. missionId .. " from " .. folderPath)

    -- Use catalog:triggerImportUI is not what we want (it's interactive)
    -- Instead, use catalog:withWriteAccessDo + catalog:addPhoto
    -- But the simplest SDK approach is catalog import via folder

    local importedPhotos = {}

    catalog:withWriteAccessDo("Sentinel Import " .. missionId, function()
        for _, photoPath in ipairs(photoPaths) do
            local ok, photo = LrTasks.pcall(function()
                return catalog:addPhoto(photoPath)
            end)
            if ok and photo then
                table.insert(importedPhotos, photo)
                logger:debug("Imported: " .. photoPath)
            else
                -- Photo might already be in catalog
                logger:debug("Skipped (may already exist): " .. photoPath)
                -- Try to find it by path
                local existing = catalog:findPhotoByPath(photoPath)
                if existing then
                    table.insert(importedPhotos, existing)
                end
            end
        end
    end)

    -- Give LR a moment to read XMP sidecars and apply develop settings
    LrTasks.sleep(2)

    -- Tell LR to read metadata from files (picks up XMP sidecars)
    catalog:withWriteAccessDo("Read XMP metadata " .. missionId, function()
        for _, photo in ipairs(importedPhotos) do
            local ok, err = LrTasks.pcall(function()
                photo:readMetadataFromFile()
            end)
            if not ok then
                logger:debug("readMetadata note: " .. tostring(err))
            end
        end
    end)

    logger:info("Imported " .. #importedPhotos .. " photos for mission " .. missionId)
    return importedPhotos
end


-- Build export settings for JPEG output
local function buildExportSettings(outputDir)
    return {
        LR_export_destinationType        = "specificFolder",
        LR_export_destinationPathPrefix  = outputDir,
        LR_export_useSubfolder           = false,
        LR_format                        = prefs.exportFormat or "JPEG",
        LR_jpeg_quality                  = prefs.exportQuality or 92,
        LR_export_colorSpace             = "sRGB",
        LR_export_bitDepth               = 8,
        LR_size_doConstrain              = prefs.exportResize or false,
        LR_size_maxHeight                = prefs.maxDimension or 5472,
        LR_size_maxWidth                 = prefs.maxDimension or 5472,
        LR_size_resolution               = 300,
        LR_size_resolutionUnits          = "inch",
        LR_outputSharpeningOn            = true,
        LR_outputSharpeningMedia         = "screen",
        LR_outputSharpeningLevel         = 2,  -- standard
        LR_metadata_keywordOptions       = "lightroomHierarchical",
        LR_removeLocationMetadata        = false,
        LR_reimportExportedPhoto         = false,
        LR_collisionHandling             = "rename",
    }
end


-- Export photos to LR_Export/{mission_id}/
local function exportMission(catalog, missionId, photos)
    local outputDir = LrPathUtils.child(prefs.exportDir, missionId)

    if not LrFileUtils.exists(outputDir) then
        LrFileUtils.createAllDirectories(outputDir)
    end

    logger:info("Exporting " .. #photos .. " photos for mission " .. missionId .. " to " .. outputDir)

    local exportSettings = buildExportSettings(outputDir)
    local exportSession = LrExportSession({
        photosToExport    = photos,
        exportSettings    = exportSettings,
    })

    local successCount = 0
    local failCount = 0
    for i, rendition in exportSession:renditions() do
        local success, pathOrMessage = rendition:waitForRender()
        if success then
            logger:debug("Exported: " .. tostring(pathOrMessage))
            successCount = successCount + 1
        else
            logger:error("Export failed for rendition " .. i .. ": " .. tostring(pathOrMessage))
            failCount = failCount + 1
        end
    end

    -- Mark photos as exported via keyword
    catalog:withWriteAccessDo("Mark Sentinel exported " .. missionId, function()
        local exportedKw = catalog:createKeyword("sentinel-exported", {}, false, nil, true)
        for _, photo in ipairs(photos) do
            photo:addKeyword(exportedKw)
        end
    end)

    logger:info("Mission " .. missionId .. " complete: " .. successCount .. " exported, " .. failCount .. " failed")
    return successCount, failCount
end


-- Process a single mission: import → apply presets (via XMP) → export
local function processMission(catalog, missionId, missionData)
    logger:info("=== Processing mission: " .. missionId .. " ===")

    -- Step 1: Import photos (XMP sidecars auto-apply develop settings)
    local photos = importPhotos(catalog, missionId, missionData)

    if #photos == 0 then
        logger:warn("No photos imported for mission " .. missionId)
        processedMissions[missionId] = true
        return
    end

    -- Step 2: Brief pause to let LR process the develop settings from XMP
    logger:info("Waiting for LR to apply develop settings...")
    LrTasks.sleep(3)

    -- Step 3: Export
    local success, fail = exportMission(catalog, missionId, photos)

    -- Mark as processed
    processedMissions[missionId] = true

    logger:info("=== Mission " .. missionId .. " done: " .. success .. "/" .. (#photos) .. " exported ===")

    -- Show bezel notification
    LrDialogs.showBezel("Sentinel: " .. missionId .. " — " .. success .. " photos exported")
end


-- Main watcher loop
LrTasks.startAsyncTask(function()
    prefs.watcherRunning = true
    logger:info("Sentinel Auto Export Watcher started (full pipeline mode)")
    logger:info("Watching: " .. prefs.importDir)
    logger:info("Exporting to: " .. prefs.exportDir)
    LrDialogs.showBezel("Sentinel Pipeline: Watcher started")

    local catalog = LrApplication.activeCatalog()
    local pollInterval = prefs.pollIntervalSec or 3

    while prefs.watcherRunning do
        local ok, err = LrTasks.pcall(function()
            -- Scan for new missions in LR_AutoImport
            local newMissions = scanForNewMissions(prefs.importDir)

            for missionId, missionData in pairs(newMissions) do
                processMission(catalog, missionId, missionData)
            end
        end)

        if not ok then
            logger:error("Watcher cycle error: " .. tostring(err))
        end

        LrTasks.sleep(pollInterval)
    end

    logger:info("Sentinel Auto Export Watcher stopped")
    LrDialogs.showBezel("Sentinel Pipeline: Watcher stopped")
end)

--[[
    Sentinel Auto Export — Init Plugin

    On startup, sets default preferences and logs plugin load.
    The auto-export watcher is started manually from Library > Plug-in Extras
    or can be set to auto-start by setting autoStartWatcher = true.
]]

local LrLogger       = import "LrLogger"
local LrPrefs        = import "LrPrefs"

local logger = LrLogger("SentinelAutoExport")
logger:enable("logfile")

local prefs = LrPrefs.prefsForPlugin()

-- Defaults
if prefs.importDir == nil then
    prefs.importDir = [[C:\Users\redle.SOULAAN\Pictures\LR_AutoImport]]
end
if prefs.exportDir == nil then
    prefs.exportDir = [[C:\Users\redle.SOULAAN\Pictures\LR_Export]]
end
if prefs.exportFormat == nil then
    prefs.exportFormat = "JPEG"
end
if prefs.exportQuality == nil then
    prefs.exportQuality = 92
end
if prefs.exportResize == nil then
    prefs.exportResize = false
end
if prefs.maxDimension == nil then
    prefs.maxDimension = 5472  -- DJI Mini 4 Pro max
end
if prefs.watcherRunning == nil then
    prefs.watcherRunning = false
end
if prefs.pollIntervalSec == nil then
    prefs.pollIntervalSec = 3
end

logger:info("Sentinel Auto Export plugin loaded.")
logger:info("  Import watch dir: " .. prefs.importDir)
logger:info("  Export dir: " .. prefs.exportDir)

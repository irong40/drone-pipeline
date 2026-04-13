--[[
    Sentinel Auto Export — Stop Watcher

    Stops the background watcher task by setting the prefs flag to false.
    Start from: Library > Plug-in Extras > Stop Auto Export Watcher
]]

local LrPrefs   = import "LrPrefs"
local LrDialogs = import "LrDialogs"
local LrLogger  = import "LrLogger"

local logger = LrLogger("SentinelAutoExport")
logger:enable("logfile")

local prefs = LrPrefs.prefsForPlugin()
prefs.watcherRunning = false

logger:info("Watcher stop requested")
LrDialogs.showBezel("Sentinel Auto Export: Stopping watcher...")

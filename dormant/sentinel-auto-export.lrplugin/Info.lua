return {
    LrSdkVersion        = 13.0,
    LrSdkMinimumVersion = 10.0,
    LrToolkitIdentifier = "com.sentinelaerial.auto-export",
    LrPluginName        = "Sentinel Auto Export",
    LrPluginInfoUrl     = "https://sentinelaerialinspections.com",

    LrLibraryMenuItems = {
        {
            title = "Start Auto Export Watcher",
            file  = "AutoExportTask.lua",
        },
        {
            title = "Stop Auto Export Watcher",
            file  = "StopWatcher.lua",
        },
    },

    LrInitPlugin = "InitPlugin.lua",

    VERSION = { major = 1, minor = 0, revision = 0, display = "1.0.0" },
}

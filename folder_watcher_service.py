"""
Sentinel Aerial Inspections — Folder Watcher Windows Service

Wraps folder_watcher.py as a Windows service so it starts automatically on boot.

Install:  python folder_watcher_service.py install
Start:    python folder_watcher_service.py start
Stop:     python folder_watcher_service.py stop
Remove:   python folder_watcher_service.py remove

Requires pywin32 (pip install pywin32).
"""

import sys

try:
    import win32serviceutil
    import win32service
    import win32event
    import servicemanager
except ImportError:
    sys.exit(
        "pywin32 is required for Windows service support. "
        "Install with: pip install pywin32"
    )

from folder_watcher import MissionFolderHandler, WATCH_DIR, DEBOUNCE_SECONDS, N8N_WEBHOOK_URL

try:
    from watchdog.observers import Observer
except ImportError:
    sys.exit("pip install watchdog")


class SentinelFolderWatcherService(win32serviceutil.ServiceFramework):
    _svc_name_ = "SentinelFolderWatcher"
    _svc_display_name_ = "Sentinel Folder Watcher"
    _svc_description_ = (
        "Monitors E:\\Sentinel\\Incoming for new mission folders and fires "
        "n8n webhooks after file writes settle."
    )

    def __init__(self, args):
        super().__init__(args)
        self.stop_event = win32event.CreateEvent(None, 0, 0, None)
        self.running = False

    def SvcStop(self):
        self.ReportServiceStatus(win32service.SERVICE_STOP_PENDING)
        self.running = False
        win32event.SetEvent(self.stop_event)

    def SvcDoRun(self):
        self.running = True
        servicemanager.LogMsg(
            servicemanager.EVENTLOG_INFORMATION_TYPE,
            servicemanager.PYS_SERVICE_STARTED,
            (self._svc_name_, ""),
        )
        self.main()

    def main(self):
        handler = MissionFolderHandler(
            watch_dir=WATCH_DIR,
            debounce_seconds=DEBOUNCE_SECONDS,
            webhook_url=N8N_WEBHOOK_URL,
        )
        observer = Observer()
        observer.schedule(handler, WATCH_DIR, recursive=True)
        observer.start()

        while self.running:
            rc = win32event.WaitForSingleObject(self.stop_event, 1000)
            if rc == win32event.WAIT_OBJECT_0:
                break

        observer.stop()
        observer.join()


if __name__ == "__main__":
    win32serviceutil.HandleCommandLine(SentinelFolderWatcherService)

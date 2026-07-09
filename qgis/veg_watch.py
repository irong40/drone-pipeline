#!/usr/bin/env python3
"""
Sentinel Aerial - vegetation-analysis trigger (filesystem watcher).

Watches a directory tree for freshly-landed NodeODM orthophotos and fires the
headless RGB vegetation analysis. This is the "no-n8n" option; if you prefer
n8n, use the Execute Command node in TRIGGER.md instead.

A NodeODM task finishes -> the pipeline downloads its output to Windows -> the
orthophoto.tif appears under the watch dir -> this watcher debounces 30s (so the
file is fully written) -> runs run_veg_analysis.bat -> outputs land next to it.

Usage:
    python veg_watch.py --watch-dir "I:\\My Drive\\Drone Facility Plans" \
                        --pattern "*orthophoto*.tif" --debounce 30
"""
import os
import sys
import time
import argparse
import subprocess
import threading
import fnmatch
from pathlib import Path

try:
    from watchdog.observers import Observer
    from watchdog.events import FileSystemEventHandler
except ImportError:
    sys.exit("pip install watchdog")

HERE = Path(__file__).resolve().parent
RUNNER = HERE / "run_veg_analysis.bat"


class OrthoHandler(FileSystemEventHandler):
    def __init__(self, pattern: str, debounce: int):
        self.pattern = pattern
        self.debounce = debounce
        self._timers: dict[str, threading.Timer] = {}
        self._seen: set[str] = set()

    def _schedule(self, path: str):
        if not fnmatch.fnmatch(os.path.basename(path).lower(), self.pattern.lower()):
            return
        if path in self._seen:
            return
        t = self._timers.get(path)
        if t:
            t.cancel()
        self._timers[path] = threading.Timer(self.debounce, self._run, [path])
        self._timers[path].start()

    def on_created(self, e):
        if not e.is_directory:
            self._schedule(e.src_path)

    def on_modified(self, e):
        if not e.is_directory:
            self._schedule(e.src_path)

    def _run(self, path: str):
        self._seen.add(path)
        out_dir = os.path.join(os.path.dirname(path), "vegetation")
        mission = os.path.basename(os.path.dirname(path)) or "ad-hoc"
        print(f"[veg-watch] analyzing {path} -> {out_dir}", flush=True)
        try:
            subprocess.run([str(RUNNER), path, out_dir, mission], check=True)
            print(f"[veg-watch] done: {out_dir}", flush=True)
        except subprocess.CalledProcessError as ex:
            print(f"[veg-watch] FAILED ({ex.returncode}) for {path}", flush=True)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--watch-dir", required=True)
    ap.add_argument("--pattern", default="*orthophoto*.tif")
    ap.add_argument("--debounce", type=int, default=30)
    args = ap.parse_args()

    if not os.path.isdir(args.watch_dir):
        sys.exit(f"watch dir does not exist: {args.watch_dir}")

    handler = OrthoHandler(args.pattern, args.debounce)
    obs = Observer()
    obs.schedule(handler, args.watch_dir, recursive=True)
    obs.start()
    print(f"[veg-watch] watching {args.watch_dir} for {args.pattern} "
          f"(debounce {args.debounce}s). Ctrl-C to stop.", flush=True)
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        obs.stop()
    obs.join()
    return 0


if __name__ == "__main__":
    sys.exit(main())

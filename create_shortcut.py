"""
Creates a desktop shortcut for the Sentinel Ingest Launcher.

Run once:
    python create_shortcut.py
"""

import os
import sys
import subprocess
from pathlib import Path


def get_desktop_path():
    """Get the actual Desktop path (handles OneDrive redirection)."""
    result = subprocess.run(
        ["powershell", "-Command", '[Environment]::GetFolderPath("Desktop")'],
        capture_output=True, text=True
    )
    desktop = result.stdout.strip()
    if desktop and os.path.isdir(desktop):
        return Path(desktop)
    # Fallback
    return Path(os.environ["USERPROFILE"]) / "Desktop"


def create_shortcut():
    try:
        import win32com.client
    except ImportError:
        # Fallback: create a .bat file on Desktop instead
        print("pywin32 not installed — creating .bat shortcut instead.")
        create_bat_shortcut()
        return

    desktop = get_desktop_path()
    shortcut_path = desktop / "Sentinel Ingest.lnk"

    script_dir = Path(__file__).resolve().parent
    launcher = script_dir / "launcher.py"
    icon_path = script_dir / "sentinel.ico"

    # Use pythonw.exe to avoid the black console window
    pythonw_exe = Path(sys.executable).parent / "pythonw.exe"
    if not pythonw_exe.exists():
        pythonw_exe = Path(sys.executable)  # fallback

    shell = win32com.client.Dispatch("WScript.Shell")
    shortcut = shell.CreateShortCut(str(shortcut_path))
    shortcut.TargetPath = str(pythonw_exe)
    shortcut.Arguments = f'"{launcher}"'
    shortcut.WorkingDirectory = str(script_dir)
    shortcut.Description = "Sentinel Aerial Inspections — Ingest Launcher"
    shortcut.WindowStyle = 1  # Normal window
    if icon_path.exists():
        shortcut.IconLocation = f"{icon_path},0"
    shortcut.save()

    print(f"Shortcut created: {shortcut_path}")


def create_bat_shortcut():
    desktop = get_desktop_path()
    bat_path = desktop / "Sentinel Ingest.bat"

    script_dir = Path(__file__).resolve().parent
    launcher = script_dir / "launcher.py"
    pythonw_exe = Path(sys.executable).parent / "pythonw.exe"
    if not pythonw_exe.exists():
        pythonw_exe = Path(sys.executable)

    bat_content = f'@echo off\ncd /d "{script_dir}"\nstart "" "{pythonw_exe}" "{launcher}"\n'

    bat_path.write_text(bat_content)
    print(f"Batch shortcut created: {bat_path}")


if __name__ == "__main__":
    create_shortcut()

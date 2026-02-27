"""
Sentinel Aerial Inspections — Desktop Launcher

Tkinter GUI for launching the ingest pipeline.
Click the desktop shortcut, fill in mission details, hit Start.

Usage:
    python launcher.py
    (or double-click the desktop shortcut)
"""

import os
import sys
import json
import uuid
import subprocess
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from datetime import datetime
from pathlib import Path

# ─── CONFIG ──────────────────────────────────────────────────────────────────

SCRIPT_DIR = Path(__file__).resolve().parent
INGEST_SCRIPT = SCRIPT_DIR / "ingest_sorter.py"
INCOMING_ROOT = r"E:\Sentinel\Incoming"
PYTHON_EXE = sys.executable

PACKAGE_TYPES = [
    "re_standard",
    "re_premium",
    "commercial_basic",
    "commercial_premium",
    "insurance_claim",
    "construction_progress",
]

# ─── LAUNCHER GUI ────────────────────────────────────────────────────────────


class LauncherApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Sentinel — Ingest Launcher")
        self.root.resizable(False, False)

        # Track mission rows
        self.missions = []

        self._build_ui()
        self._center_window()

    def _center_window(self):
        self.root.update_idletasks()
        w = self.root.winfo_width()
        h = self.root.winfo_height()
        x = (self.root.winfo_screenwidth() // 2) - (w // 2)
        y = (self.root.winfo_screenheight() // 2) - (h // 2)
        self.root.geometry(f"+{x}+{y}")

    def _build_ui(self):
        # ── Header
        header = ttk.Frame(self.root, padding=10)
        header.pack(fill="x")
        ttk.Label(header, text="Sentinel Ingest Launcher",
                  font=("Segoe UI", 14, "bold")).pack(anchor="w")
        ttk.Label(header, text="Fill in mission details, then click Start.",
                  font=("Segoe UI", 9)).pack(anchor="w")

        ttk.Separator(self.root, orient="horizontal").pack(fill="x", padx=10)

        # ── Source folder
        src_frame = ttk.LabelFrame(self.root, text="Source Folder (SD Card)", padding=10)
        src_frame.pack(fill="x", padx=10, pady=(10, 5))

        row = ttk.Frame(src_frame)
        row.pack(fill="x")
        self.source_var = tk.StringVar()
        ttk.Entry(row, textvariable=self.source_var, width=60).pack(side="left", fill="x", expand=True)
        ttk.Button(row, text="Browse...", command=self._browse_source).pack(side="left", padx=(5, 0))

        # ── Missions frame
        missions_outer = ttk.LabelFrame(self.root, text="Missions", padding=10)
        missions_outer.pack(fill="both", expand=True, padx=10, pady=5)

        # Column headers
        hdr = ttk.Frame(missions_outer)
        hdr.pack(fill="x")
        ttk.Label(hdr, text="Mission #", width=10, font=("Segoe UI", 8, "bold")).pack(side="left", padx=2)
        ttk.Label(hdr, text="Package Type", width=22, font=("Segoe UI", 8, "bold")).pack(side="left", padx=2)
        ttk.Label(hdr, text="Date", width=12, font=("Segoe UI", 8, "bold")).pack(side="left", padx=2)
        ttk.Label(hdr, text="Seq Start", width=10, font=("Segoe UI", 8, "bold")).pack(side="left", padx=2)
        ttk.Label(hdr, text="Seq End", width=10, font=("Segoe UI", 8, "bold")).pack(side="left", padx=2)

        self.missions_container = ttk.Frame(missions_outer)
        self.missions_container.pack(fill="both", expand=True)

        # Add first mission row
        self._add_mission_row()

        btn_row = ttk.Frame(missions_outer)
        btn_row.pack(fill="x", pady=(5, 0))
        ttk.Button(btn_row, text="+ Add Mission", command=self._add_mission_row).pack(side="left")
        ttk.Button(btn_row, text="- Remove Last", command=self._remove_mission_row).pack(side="left", padx=5)

        # ── Options
        opts_frame = ttk.LabelFrame(self.root, text="Options", padding=10)
        opts_frame.pack(fill="x", padx=10, pady=5)

        self.webhook_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(opts_frame, text="Fire n8n webhook after ingest",
                        variable=self.webhook_var).pack(anchor="w")

        self.dry_run_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(opts_frame, text="Dry run (preview only, no file copying)",
                        variable=self.dry_run_var).pack(anchor="w")

        # ── Action buttons
        action_frame = ttk.Frame(self.root, padding=10)
        action_frame.pack(fill="x")

        self.start_btn = ttk.Button(action_frame, text="Start Ingest",
                                     command=self._start_ingest)
        self.start_btn.pack(side="right")

        ttk.Button(action_frame, text="Quit", command=self.root.quit).pack(side="right", padx=5)

        # ── Status bar
        self.status_var = tk.StringVar(value="Ready")
        status_bar = ttk.Label(self.root, textvariable=self.status_var,
                               relief="sunken", padding=(5, 2))
        status_bar.pack(fill="x", side="bottom")

    def _add_mission_row(self):
        row_frame = ttk.Frame(self.missions_container)
        row_frame.pack(fill="x", pady=1)

        mission_num = tk.StringVar()
        package_type = tk.StringVar(value=PACKAGE_TYPES[0])
        date_var = tk.StringVar(value=datetime.now().strftime("%Y%m%d"))
        seq_start = tk.StringVar(value="1")
        seq_end = tk.StringVar()

        ttk.Entry(row_frame, textvariable=mission_num, width=10).pack(side="left", padx=2)
        combo = ttk.Combobox(row_frame, textvariable=package_type, values=PACKAGE_TYPES,
                             width=20, state="readonly")
        combo.pack(side="left", padx=2)
        ttk.Entry(row_frame, textvariable=date_var, width=12).pack(side="left", padx=2)
        ttk.Entry(row_frame, textvariable=seq_start, width=10).pack(side="left", padx=2)
        ttk.Entry(row_frame, textvariable=seq_end, width=10).pack(side="left", padx=2)

        self.missions.append({
            "frame": row_frame,
            "mission_num": mission_num,
            "package_type": package_type,
            "date": date_var,
            "seq_start": seq_start,
            "seq_end": seq_end,
        })

    def _remove_mission_row(self):
        if len(self.missions) <= 1:
            return
        row = self.missions.pop()
        row["frame"].destroy()

    def _browse_source(self):
        folder = filedialog.askdirectory(title="Select SD card folder (e.g. E:/DCIM/DJI_001)")
        if folder:
            self.source_var.set(folder)

    def _validate(self):
        """Validate all inputs. Returns (missions_config, error_msg)."""
        source = self.source_var.get().strip()
        if not source:
            return None, "Please select a source folder."
        if not os.path.isdir(source):
            return None, f"Source folder not found: {source}"

        missions_config = []
        for i, m in enumerate(self.missions):
            num_str = m["mission_num"].get().strip()
            if not num_str:
                return None, f"Mission #{i+1}: Mission number is required."
            try:
                num = int(num_str)
            except ValueError:
                return None, f"Mission #{i+1}: Mission number must be a number."

            date_str = m["date"].get().strip()
            if len(date_str) != 8 or not date_str.isdigit():
                return None, f"Mission #{i+1}: Date must be YYYYMMDD format."

            seq_s = m["seq_start"].get().strip()
            seq_e = m["seq_end"].get().strip()
            if not seq_s or not seq_e:
                return None, f"Mission #{i+1}: Sequence start and end are required."
            try:
                seq_start = int(seq_s)
                seq_end = int(seq_e)
            except ValueError:
                return None, f"Mission #{i+1}: Sequence values must be numbers."

            if seq_start > seq_end:
                return None, f"Mission #{i+1}: Sequence start must be <= end."

            missions_config.append({
                "mission_id": str(uuid.uuid4()),
                "mission_number": num,
                "package_type": m["package_type"].get(),
                "date": date_str,
                "sequence_start": seq_start,
                "sequence_end": seq_end,
            })

        return missions_config, None

    def _start_ingest(self):
        missions_config, error = self._validate()
        if error:
            messagebox.showerror("Validation Error", error)
            return

        # Write temp missions JSON
        temp_json = SCRIPT_DIR / ".launcher_missions.json"
        with open(temp_json, "w") as f:
            json.dump(missions_config, f, indent=2)

        # Build command
        cmd = [PYTHON_EXE, str(INGEST_SCRIPT), self.source_var.get().strip(),
               "--missions", str(temp_json)]

        if self.webhook_var.get():
            cmd.append("--webhook")
        if self.dry_run_var.get():
            cmd.append("--dry-run")

        # Disable start button during run
        self.start_btn.configure(state="disabled")
        self.status_var.set("Running ingest...")
        self.root.update()

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                cwd=str(SCRIPT_DIR),
                timeout=600,  # 10 minute timeout
            )

            # Clean up temp file
            try:
                temp_json.unlink()
            except OSError:
                pass

            if result.returncode == 0:
                self.status_var.set("Ingest complete!")
                messagebox.showinfo("Success", f"Ingest complete!\n\n{result.stdout[-500:] if result.stdout else 'Done.'}")
            else:
                self.status_var.set("Ingest failed.")
                messagebox.showerror("Ingest Failed",
                                     f"Exit code: {result.returncode}\n\n"
                                     f"{result.stderr[-500:] if result.stderr else result.stdout[-500:] if result.stdout else 'No output.'}")

        except subprocess.TimeoutExpired:
            self.status_var.set("Ingest timed out.")
            messagebox.showerror("Timeout", "Ingest timed out after 10 minutes.")
        except Exception as e:
            self.status_var.set("Error.")
            messagebox.showerror("Error", str(e))
        finally:
            self.start_btn.configure(state="normal")


# ─── MAIN ────────────────────────────────────────────────────────────────────

def main():
    root = tk.Tk()
    LauncherApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()

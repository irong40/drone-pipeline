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
INCOMING_ROOT = r"E:\incoming"
PYTHON_EXE = sys.executable

PACKAGE_TYPES = [
    "re_basic",
    "re_standard",
    "re_premium",
    "commercial_basic",
    "commercial_premium",
    "insurance_claim",
    "construction_progress",
    "site_survey",
    "environmental_survey",
    "census_thermal",
]

# Default ACL (Above Canopy Level) requirements per mission type (feet)
DEFAULT_ACL = {
    "re_basic": 150,
    "re_standard": 150,
    "re_premium": 200,
    "commercial_basic": 200,
    "commercial_premium": 250,
    "insurance_claim": 100,
    "construction_progress": 200,
    "site_survey": 250,
    "environmental_survey": 300,
    "census_thermal": 300,
}

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

        # ── ACL Calibration
        acl_frame = ttk.LabelFrame(self.root, text="ACL Calibration (Above Canopy Level)", padding=10)
        acl_frame.pack(fill="x", padx=10, pady=5)

        acl_row1 = ttk.Frame(acl_frame)
        acl_row1.pack(fill="x")
        ttk.Label(acl_row1, text="Canopy height (ft):", width=20).pack(side="left")
        self.canopy_height_var = tk.StringVar(value="0")
        ttk.Entry(acl_row1, textvariable=self.canopy_height_var, width=10).pack(side="left", padx=2)
        ttk.Label(acl_row1, text="From rangefinder or thermal photo",
                  font=("Segoe UI", 8)).pack(side="left", padx=(10, 0))

        acl_row2 = ttk.Frame(acl_frame)
        acl_row2.pack(fill="x", pady=(3, 0))
        ttk.Label(acl_row2, text="Required ACL (ft):", width=20).pack(side="left")
        self.required_acl_var = tk.StringVar(value="200")
        ttk.Entry(acl_row2, textvariable=self.required_acl_var, width=10).pack(side="left", padx=2)

        acl_row3 = ttk.Frame(acl_frame)
        acl_row3.pack(fill="x", pady=(3, 0))
        ttk.Label(acl_row3, text="Recommended altitude:", width=20).pack(side="left")
        self.rec_alt_var = tk.StringVar(value="—")
        ttk.Label(acl_row3, textvariable=self.rec_alt_var,
                  font=("Segoe UI", 10, "bold")).pack(side="left")

        ttk.Button(acl_frame, text="Calculate", command=self._calc_acl).pack(anchor="w", pady=(5, 0))
        ttk.Button(acl_frame, text="Read from thermal photo...",
                   command=self._read_canopy_from_photo).pack(anchor="w", pady=(3, 0))

        # ── Parcel Boundary Lookup
        parcel_frame = ttk.LabelFrame(self.root, text="Parcel Boundary (KML for WaypointMap)", padding=10)
        parcel_frame.pack(fill="x", padx=10, pady=5)

        parcel_row = ttk.Frame(parcel_frame)
        parcel_row.pack(fill="x")
        ttk.Label(parcel_row, text="Property address:", width=18).pack(side="left")
        self.parcel_address_var = tk.StringVar()
        ttk.Entry(parcel_row, textvariable=self.parcel_address_var, width=45).pack(side="left", padx=2, fill="x", expand=True)

        parcel_row2 = ttk.Frame(parcel_frame)
        parcel_row2.pack(fill="x", pady=(3, 0))
        ttk.Label(parcel_row2, text="Buffer (ft):", width=18).pack(side="left")
        self.parcel_buffer_var = tk.StringVar(value="0")
        ttk.Entry(parcel_row2, textvariable=self.parcel_buffer_var, width=10).pack(side="left", padx=2)
        ttk.Button(parcel_row2, text="Lookup & Export KML",
                   command=self._lookup_parcel).pack(side="left", padx=(10, 0))

        self.parcel_result_var = tk.StringVar(value="")
        ttk.Label(parcel_frame, textvariable=self.parcel_result_var,
                  font=("Segoe UI", 8), wraplength=500).pack(anchor="w", pady=(3, 0))

        # ── Options
        opts_frame = ttk.LabelFrame(self.root, text="Options", padding=10)
        opts_frame.pack(fill="x", padx=10, pady=5)

        self.no_webhook_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(opts_frame, text="Skip n8n webhook after ingest",
                        variable=self.no_webhook_var).pack(anchor="w")

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
        combo.bind("<<ComboboxSelected>>", lambda e: self._on_package_change(package_type.get()))
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

    def _on_package_change(self, package_type):
        """Update default ACL when package type changes."""
        default = DEFAULT_ACL.get(package_type, 200)
        self.required_acl_var.set(str(default))
        self._calc_acl()

    def _calc_acl(self):
        """Calculate recommended flight altitude from canopy height + required ACL."""
        try:
            canopy = float(self.canopy_height_var.get() or 0)
            acl = float(self.required_acl_var.get() or 200)
            rec = canopy + acl
            self.rec_alt_var.set(f"{rec:.0f} ft AGL")
        except ValueError:
            self.rec_alt_var.set("Invalid input")

    def _read_canopy_from_photo(self):
        """Read canopy height from a thermal photo's ObjectDistance EXIF field."""
        filepath = filedialog.askopenfilename(
            title="Select thermal calibration photo",
            filetypes=[
                ("Thermal photos", "*.jpg *.jpeg *.rjpeg *.tif *.tiff"),
                ("All files", "*.*"),
            ],
        )
        if not filepath:
            return

        try:
            from sentinel_core.metadata import extract_thermal_metadata
            thermal = extract_thermal_metadata(filepath)

            if not thermal:
                messagebox.showwarning("No Data", "No thermal metadata found in this photo.")
                return

            if "canopy_height" in thermal:
                height_m = thermal["canopy_height"]
                height_ft = height_m * 3.28084
                self.canopy_height_var.set(f"{height_ft:.0f}")
                self._calc_acl()
                messagebox.showinfo(
                    "ACL Calibration",
                    f"Rangefinder distance: {thermal.get('object_distance', '?')} m\n"
                    f"Drone AGL: {thermal.get('relative_altitude', '?')} m\n"
                    f"Canopy height: {height_m:.1f} m ({height_ft:.0f} ft)\n\n"
                    f"Recommended altitude updated.",
                )
            elif "object_distance" in thermal:
                dist = thermal["object_distance"]
                agl = thermal.get("relative_altitude", 0)
                messagebox.showinfo(
                    "Partial Data",
                    f"ObjectDistance: {dist} m\n"
                    f"Drone AGL: {agl} m\n\n"
                    f"Gimbal pitch was {thermal.get('gimbal_pitch', '?')}° — "
                    f"for accurate canopy height, point camera straight down (-90°).",
                )
            else:
                messagebox.showwarning(
                    "No Rangefinder Data",
                    "This photo has no ObjectDistance field.\n"
                    "Enable the rangefinder before taking the calibration photo.",
                )
        except ImportError:
            messagebox.showerror("Error", "sentinel_core not installed. Run: pip install -e D:\\Projects\\sentinel-core")
        except Exception as e:
            messagebox.showerror("Error", f"Failed to read thermal metadata: {e}")

    def _lookup_parcel(self):
        """Look up parcel boundary and export KML."""
        address = self.parcel_address_var.get().strip()
        if not address:
            messagebox.showwarning("Missing Address", "Enter a property address first.")
            return

        buffer_ft = float(self.parcel_buffer_var.get() or 0)
        self.parcel_result_var.set("Looking up parcel...")
        self.root.update()

        try:
            from parcel_lookup import run as parcel_run
            result = parcel_run(address=address, buffer_ft=buffer_ft)

            self.parcel_result_var.set(
                f"Found: {result['parcel_id']} | {result['acres']} acres | "
                f"Owner: {result.get('owner', 'N/A')}"
            )

            kml_path = result["kml_path"]
            msg = (
                f"Parcel ID: {result['parcel_id']}\n"
                f"Area: {result['acres']} acres\n"
                f"Owner: {result.get('owner', 'N/A')}\n"
                f"Vertices: {result['vertex_count']}\n\n"
                f"KML saved to:\n{kml_path}\n\n"
                f"Load this into WaypointMap to define your survey area."
            )

            if messagebox.askyesno("Parcel Found", msg + "\n\nOpen KML file location?"):
                os.startfile(str(Path(kml_path).parent))

        except Exception as e:
            self.parcel_result_var.set(f"Error: {e}")
            messagebox.showerror("Parcel Lookup Failed", str(e))

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
                "canopy_height_ft": float(self.canopy_height_var.get() or 0),
                "required_acl_ft": float(self.required_acl_var.get() or 200),
                "recommended_alt_ft": float(self.canopy_height_var.get() or 0) + float(self.required_acl_var.get() or 200),
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

        if self.no_webhook_var.get():
            cmd.append("--no-webhook")
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

"""
Sentinel Aerial Inspections — Desktop Photo Loader

CustomTkinter GUI for browsing drone photos, previewing thumbnails,
viewing EXIF/GPS data, assigning missions, and launching the ingest pipeline.

Usage:
    python launcher.py
    (or double-click the desktop shortcut)
"""

import os
import sys
import json
import uuid
import subprocess
import threading
import tkinter as tk
from tkinter import filedialog, messagebox
from pathlib import Path
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor

try:
    import customtkinter as ctk
except ImportError:
    sys.exit("Missing dependency: pip install customtkinter")

try:
    from PIL import Image, ImageTk
    from PIL.ExifTags import Base as ExifBase
except ImportError:
    sys.exit("Missing dependency: pip install Pillow")

# Optional drag-and-drop
try:
    import tkinterdnd2

    HAS_DND = True
except ImportError:
    HAS_DND = False

# ─── LOCAL IMPORTS ────────────────────────────────────────────────────────────

from pipeline_utils import PHOTO_EXTS, VIDEO_EXTS, extract_sequence_number
from platform_detect import detect_from_exif, detect_from_filename
from ingest_sorter import scan_sd_card, MISSION_GAP_MINUTES

# ─── CONFIG ──────────────────────────────────────────────────────────────────

SCRIPT_DIR = Path(__file__).resolve().parent
INGEST_SCRIPT = SCRIPT_DIR / "ingest_sorter.py"
INCOMING_ROOT = r"E:\Sentinel\Incoming"
PYTHON_EXE = sys.executable
ICON_PATH = SCRIPT_DIR / "sentinel.ico"
RECENT_FILE = SCRIPT_DIR / ".recent_folders.json"

THUMB_SIZE = 120
THUMB_COLS = 4
MAX_RECENT = 8

PACKAGE_TYPES = [
    "re_standard",
    "re_premium",
    "commercial_basic",
    "commercial_premium",
    "insurance_claim",
    "construction_progress",
]

QUALITY_LEVELS = ["High", "Medium", "Low"]

# CustomTkinter appearance
ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")

# Mission color palette for thumbnail borders
MISSION_COLORS = [
    "#3B82F6",  # blue
    "#10B981",  # green
    "#F59E0B",  # amber
    "#EF4444",  # red
    "#8B5CF6",  # violet
    "#EC4899",  # pink
    "#06B6D4",  # cyan
    "#F97316",  # orange
]


# ─── HELPERS ─────────────────────────────────────────────────────────────────


def _load_recent():
    """Load recent folders list from disk."""
    try:
        if RECENT_FILE.exists():
            with open(RECENT_FILE, "r") as f:
                data = json.load(f)
            return [p for p in data if os.path.isdir(p)][:MAX_RECENT]
    except (json.JSONDecodeError, OSError):
        pass
    return []


def _save_recent(folders):
    """Save recent folders list to disk."""
    try:
        with open(RECENT_FILE, "w") as f:
            json.dump(folders[:MAX_RECENT], f)
    except OSError:
        pass


def _add_recent(path, recent_list):
    """Add a path to the front of recent list, deduplicating."""
    norm = os.path.normpath(path)
    recent_list = [p for p in recent_list if os.path.normpath(p) != norm]
    recent_list.insert(0, norm)
    return recent_list[:MAX_RECENT]


def _read_exif(filepath):
    """Read EXIF data from a photo. Returns dict of display-friendly fields."""
    info = {}
    try:
        img = Image.open(filepath)
        exif = img.getexif()
        if not exif:
            return info

        info["Camera"] = exif.get(272, "Unknown")  # Model
        info["Make"] = exif.get(271, "")  # Make

        # Date
        date_str = exif.get(36867) or exif.get(306, "")  # DateTimeOriginal or DateTime
        if date_str:
            info["Date"] = date_str

        # Image size
        info["Resolution"] = f"{img.width} x {img.height}"
        info["File Size"] = _fmt_size(os.path.getsize(filepath))

        # GPS
        gps_ifd = exif.get_ifd(0x8825)  # GPSInfo IFD
        if gps_ifd:
            lat = _gps_to_decimal(gps_ifd.get(2), gps_ifd.get(1))
            lon = _gps_to_decimal(gps_ifd.get(4), gps_ifd.get(3))
            if lat is not None and lon is not None:
                info["GPS"] = f"{lat:.6f}, {lon:.6f}"
                info["_lat"] = lat
                info["_lon"] = lon
            alt = gps_ifd.get(6)
            if alt is not None:
                alt_val = float(alt) if not isinstance(alt, tuple) else float(alt[0]) / float(alt[1]) if len(alt) == 2 else float(alt)
                info["Altitude"] = f"{alt_val:.1f}m"

        # Sequence number from filename
        seq = extract_sequence_number(os.path.basename(filepath))
        if seq:
            info["Sequence"] = f"{seq:04d}"

        # Platform detection
        platform = detect_from_filename(os.path.basename(filepath))
        if platform:
            info["Platform"] = platform

    except Exception:
        pass
    return info


def _read_exif_detailed(filepath):
    """Read detailed EXIF including gimbal angles via exiftool if available."""
    info = _read_exif(filepath)

    # Try exiftool for XMP drone data (gimbal angles, etc.)
    try:
        import exiftool

        with exiftool.ExifToolHelper() as et:
            meta_list = et.get_metadata(str(filepath))
            if meta_list:
                meta = meta_list[0]
                gimbal_pitch = meta.get("XMP:GimbalPitchDegree")
                gimbal_yaw = meta.get("XMP:GimbalYawDegree")
                gimbal_roll = meta.get("XMP:GimbalRollDegree")
                if gimbal_pitch is not None:
                    info["Gimbal Pitch"] = f"{float(gimbal_pitch):.1f}\u00b0"
                if gimbal_yaw is not None:
                    info["Gimbal Yaw"] = f"{float(gimbal_yaw):.1f}\u00b0"
                if gimbal_roll is not None:
                    info["Gimbal Roll"] = f"{float(gimbal_roll):.1f}\u00b0"
                abs_alt = meta.get("XMP:AbsoluteAltitude")
                rel_alt = meta.get("XMP:RelativeAltitude")
                if rel_alt is not None:
                    info["Alt (AGL)"] = f"{float(rel_alt):.1f}m"
                if abs_alt is not None:
                    info["Alt (Abs)"] = f"{float(abs_alt):.1f}m"
                xmp_model = meta.get("XMP:Model") or meta.get("EXIF:Model")
                if xmp_model:
                    info["Camera"] = xmp_model
    except Exception:
        pass

    return info


def _gps_to_decimal(coords, ref):
    """Convert GPS EXIF tuple to decimal degrees."""
    if not coords or not ref:
        return None
    try:
        d, m, s = [float(x) for x in coords]
        decimal = d + m / 60 + s / 3600
        if ref in ("S", "W"):
            decimal = -decimal
        return decimal
    except (TypeError, ValueError, ZeroDivisionError):
        return None


def _fmt_size(nbytes):
    """Format file size in human-readable form."""
    for unit in ("B", "KB", "MB", "GB"):
        if nbytes < 1024:
            return f"{nbytes:.1f} {unit}"
        nbytes /= 1024
    return f"{nbytes:.1f} TB"


def _is_media(fname):
    """Check if a filename is a supported photo or video."""
    ext = os.path.splitext(fname)[1].lstrip(".").upper()
    return ext in PHOTO_EXTS or ext in VIDEO_EXTS


def _is_photo(fname):
    """Check if a filename is a supported photo."""
    ext = os.path.splitext(fname)[1].lstrip(".").upper()
    return ext in PHOTO_EXTS


# ─── PLACEHOLDER IMAGE ──────────────────────────────────────────────────────


def _create_placeholder(size=THUMB_SIZE):
    """Create a gray placeholder image for loading thumbnails."""
    img = Image.new("RGB", (size, size), color=(60, 60, 60))
    return ImageTk.PhotoImage(img)


# ─── MAIN APPLICATION ───────────────────────────────────────────────────────


class SentinelPhotoLoader(ctk.CTk):
    """Main application window for the Sentinel Photo Loader."""

    def __init__(self):
        super().__init__()

        self.title("Sentinel Photo Loader")
        self.geometry("960x750")
        self.minsize(800, 600)

        # Set icon
        if ICON_PATH.exists():
            try:
                self.iconbitmap(str(ICON_PATH))
            except Exception:
                pass

        # State
        self.source_path = ""
        self.scanned_files = []  # list of dicts from scan_sd_card
        self.photo_files = []  # photo-only subset for thumbnails
        self.thumb_cache = {}  # filepath -> PhotoImage
        self.thumb_widgets = []  # list of (label, filepath) for grid
        self.missions = []  # list of mission row dicts
        self.recent_folders = _load_recent()
        self.detected_platform = ""
        self.selected_thumb_idx = None
        self.ingest_running = False
        self.executor = ThreadPoolExecutor(max_workers=4)

        # Placeholder image (created after mainloop starts)
        self._placeholder = None

        self._build_ui()
        self._center_window()

        # Enable drag-and-drop if available
        if HAS_DND:
            try:
                self.drop_target_register(tkinterdnd2.DND_FILES)
                self.dnd_bind("<<Drop>>", self._on_drop)
            except Exception:
                pass  # DnD not critical

    def _center_window(self):
        self.update_idletasks()
        w = self.winfo_width()
        h = self.winfo_height()
        x = (self.winfo_screenwidth() // 2) - (w // 2)
        y = (self.winfo_screenheight() // 2) - (h // 2)
        self.geometry(f"+{x}+{y}")

    # ── UI BUILD ─────────────────────────────────────────────────────────────

    def _build_ui(self):
        # Configure grid weights for the main window
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(2, weight=1)  # thumbnail area stretches

        # ── Source bar (row 0) ───────────────────────────────────────────────
        source_frame = ctk.CTkFrame(self)
        source_frame.grid(row=0, column=0, sticky="ew", padx=10, pady=(10, 5))
        source_frame.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(source_frame, text="Source:", font=ctk.CTkFont(size=13, weight="bold")).grid(
            row=0, column=0, padx=(10, 5), pady=8
        )

        self.source_var = ctk.StringVar()
        self.source_entry = ctk.CTkEntry(source_frame, textvariable=self.source_var, width=400)
        self.source_entry.grid(row=0, column=1, sticky="ew", padx=5, pady=8)

        ctk.CTkButton(source_frame, text="Browse", width=80, command=self._browse_source).grid(
            row=0, column=2, padx=5, pady=8
        )

        # Recent folders dropdown
        self.recent_menu_var = ctk.StringVar(value="Recent")
        self.recent_menu = ctk.CTkOptionMenu(
            source_frame,
            variable=self.recent_menu_var,
            values=self.recent_folders if self.recent_folders else ["(none)"],
            width=100,
            command=self._on_recent_select,
        )
        self.recent_menu.grid(row=0, column=3, padx=(5, 10), pady=8)

        # ── Middle area: thumbnail grid + EXIF panel (row 2) ─────────────────
        middle_frame = ctk.CTkFrame(self)
        middle_frame.grid(row=2, column=0, sticky="nsew", padx=10, pady=5)
        middle_frame.grid_columnconfigure(0, weight=3)
        middle_frame.grid_columnconfigure(1, weight=1)
        middle_frame.grid_rowconfigure(0, weight=1)

        # Thumbnail grid (scrollable)
        self.thumb_scroll = ctk.CTkScrollableFrame(middle_frame, label_text="Photos")
        self.thumb_scroll.grid(row=0, column=0, sticky="nsew", padx=(5, 2), pady=5)
        for i in range(THUMB_COLS):
            self.thumb_scroll.grid_columnconfigure(i, weight=1)

        # Status label below thumbnail area
        self.scan_status_var = ctk.StringVar(value="No folder selected")
        self.scan_status = ctk.CTkLabel(
            middle_frame, textvariable=self.scan_status_var,
            font=ctk.CTkFont(size=11), text_color="gray"
        )
        self.scan_status.grid(row=1, column=0, sticky="w", padx=10, pady=(0, 5))

        # EXIF info panel (right side)
        self.exif_frame = ctk.CTkFrame(middle_frame, width=260)
        self.exif_frame.grid(row=0, column=1, rowspan=2, sticky="nsew", padx=(2, 5), pady=5)
        self.exif_frame.grid_propagate(False)

        ctk.CTkLabel(self.exif_frame, text="EXIF Info", font=ctk.CTkFont(size=13, weight="bold")).pack(
            anchor="w", padx=10, pady=(10, 5)
        )

        self.exif_text = ctk.CTkTextbox(self.exif_frame, width=240, wrap="word", state="disabled")
        self.exif_text.pack(fill="both", expand=True, padx=5, pady=(0, 5))

        self.map_btn = ctk.CTkButton(
            self.exif_frame, text="Open Map", width=100, state="disabled",
            command=self._open_map
        )
        self.map_btn.pack(pady=(0, 10))

        # ── Missions section (row 3) ─────────────────────────────────────────
        missions_frame = ctk.CTkFrame(self)
        missions_frame.grid(row=3, column=0, sticky="ew", padx=10, pady=5)
        missions_frame.grid_columnconfigure(0, weight=1)

        missions_header = ctk.CTkFrame(missions_frame, fg_color="transparent")
        missions_header.pack(fill="x", padx=10, pady=(5, 0))
        ctk.CTkLabel(missions_header, text="Missions", font=ctk.CTkFont(size=13, weight="bold")).pack(
            side="left"
        )

        # Column headers
        col_hdr = ctk.CTkFrame(missions_frame, fg_color="transparent")
        col_hdr.pack(fill="x", padx=10, pady=(5, 0))
        for text, w in [("#", 50), ("Package Type", 180), ("Date", 100), ("Seq Start", 80), ("Seq End", 80)]:
            ctk.CTkLabel(col_hdr, text=text, width=w, font=ctk.CTkFont(size=11, weight="bold")).pack(
                side="left", padx=2
            )

        # Mission rows container
        self.missions_container = ctk.CTkFrame(missions_frame, fg_color="transparent")
        self.missions_container.pack(fill="x", padx=10, pady=2)

        # Add first row
        self._add_mission_row()

        # Mission buttons
        btn_row = ctk.CTkFrame(missions_frame, fg_color="transparent")
        btn_row.pack(fill="x", padx=10, pady=(2, 8))
        ctk.CTkButton(btn_row, text="+ Add Mission", width=120, command=self._add_mission_row).pack(
            side="left", padx=2
        )
        ctk.CTkButton(btn_row, text="- Remove", width=90, command=self._remove_mission_row).pack(
            side="left", padx=2
        )
        self.auto_detect_btn = ctk.CTkButton(
            btn_row, text="Auto-Detect Missions", width=160,
            command=self._auto_detect_missions, state="disabled"
        )
        self.auto_detect_btn.pack(side="left", padx=2)

        # ── Options + Actions (row 4) ────────────────────────────────────────
        bottom_frame = ctk.CTkFrame(self)
        bottom_frame.grid(row=4, column=0, sticky="ew", padx=10, pady=(5, 10))
        bottom_frame.grid_columnconfigure(2, weight=1)

        # Checkboxes
        opts_left = ctk.CTkFrame(bottom_frame, fg_color="transparent")
        opts_left.grid(row=0, column=0, sticky="w", padx=10, pady=5)

        self.webhook_var = ctk.BooleanVar(value=False)
        ctk.CTkCheckBox(opts_left, text="Fire n8n webhook", variable=self.webhook_var).pack(
            side="left", padx=(0, 15)
        )

        self.dry_run_var = ctk.BooleanVar(value=False)
        ctk.CTkCheckBox(opts_left, text="Dry run", variable=self.dry_run_var).pack(
            side="left", padx=(0, 15)
        )

        # Quality dropdown
        ctk.CTkLabel(opts_left, text="Quality:").pack(side="left", padx=(0, 5))
        self.quality_var = ctk.StringVar(value="High")
        ctk.CTkOptionMenu(opts_left, variable=self.quality_var, values=QUALITY_LEVELS, width=90).pack(
            side="left"
        )

        # Progress bar
        self.progress_var = ctk.DoubleVar(value=0)
        self.progress_bar = ctk.CTkProgressBar(bottom_frame, variable=self.progress_var, width=400)
        self.progress_bar.grid(row=1, column=0, columnspan=3, sticky="ew", padx=10, pady=(5, 2))
        self.progress_bar.set(0)

        # Status text + Start button
        status_row = ctk.CTkFrame(bottom_frame, fg_color="transparent")
        status_row.grid(row=2, column=0, columnspan=3, sticky="ew", padx=10, pady=(0, 5))
        status_row.grid_columnconfigure(0, weight=1)

        self.status_var = ctk.StringVar(value="Ready")
        ctk.CTkLabel(status_row, textvariable=self.status_var, text_color="gray").grid(
            row=0, column=0, sticky="w"
        )

        self.start_btn = ctk.CTkButton(
            status_row, text="Start Ingest", width=140,
            font=ctk.CTkFont(size=13, weight="bold"),
            command=self._start_ingest
        )
        self.start_btn.grid(row=0, column=1, sticky="e")

    # ── SOURCE FOLDER ────────────────────────────────────────────────────────

    def _browse_source(self):
        folder = filedialog.askdirectory(title="Select folder with drone photos")
        if folder:
            self._set_source(folder)

    def _on_recent_select(self, choice):
        if choice and choice != "(none)":
            self._set_source(choice)

    def _on_drop(self, event):
        """Handle drag-and-drop of folders."""
        path = event.data.strip().strip("{}")
        if os.path.isdir(path):
            self._set_source(path)
        elif os.path.isfile(path):
            self._set_source(os.path.dirname(path))

    def _set_source(self, folder):
        """Set source folder and trigger scan."""
        self.source_var.set(folder)
        self.source_path = folder

        # Update recent list
        self.recent_folders = _add_recent(folder, self.recent_folders)
        _save_recent(self.recent_folders)
        self.recent_menu.configure(values=self.recent_folders)

        # Scan in background
        self._scan_folder(folder)

    def _scan_folder(self, folder):
        """Scan folder for DJI files in a background thread."""
        self.scan_status_var.set("Scanning...")
        self.auto_detect_btn.configure(state="disabled")
        self._clear_thumbnails()

        def do_scan():
            files = scan_sd_card(folder)
            self.after(0, lambda: self._on_scan_complete(files, folder))

        threading.Thread(target=do_scan, daemon=True).start()

    def _on_scan_complete(self, files, folder):
        """Called on main thread after scan completes."""
        self.scanned_files = files
        self.photo_files = [f for f in files if f["extension"] in PHOTO_EXTS]

        # Count file types
        photo_count = len(self.photo_files)
        video_count = sum(1 for f in files if f["extension"] in VIDEO_EXTS)

        # Detect platform
        platforms = set(f["platform"] for f in files if f["platform"])
        self.detected_platform = platforms.pop() if len(platforms) == 1 else "unknown"

        status_parts = []
        if photo_count:
            status_parts.append(f"{photo_count} photos")
        if video_count:
            status_parts.append(f"{video_count} video")
        status_parts.append(f"Platform: {self.detected_platform}")
        self.scan_status_var.set("Found: " + ", ".join(status_parts))

        if self.scanned_files:
            self.auto_detect_btn.configure(state="normal")

        # Load thumbnails
        if self.photo_files:
            self._load_thumbnails()

    # ── THUMBNAIL GRID ───────────────────────────────────────────────────────

    def _clear_thumbnails(self):
        """Remove all thumbnail widgets."""
        for widget in self.thumb_scroll.winfo_children():
            widget.destroy()
        self.thumb_widgets.clear()
        self.thumb_cache.clear()
        self.selected_thumb_idx = None

    def _load_thumbnails(self):
        """Start lazy-loading thumbnails in batches."""
        if not self._placeholder:
            self._placeholder = _create_placeholder()

        # Create placeholder grid
        for idx, f in enumerate(self.photo_files):
            row = idx // THUMB_COLS
            col = idx % THUMB_COLS

            frame = ctk.CTkFrame(self.thumb_scroll, width=THUMB_SIZE + 8, height=THUMB_SIZE + 24)
            frame.grid(row=row, column=col, padx=4, pady=4)
            frame.grid_propagate(False)

            label = tk.Label(
                frame, image=self._placeholder, bg="#2b2b2b",
                width=THUMB_SIZE, height=THUMB_SIZE
            )
            label.pack(padx=2, pady=2)
            label.bind("<Button-1>", lambda e, i=idx: self._on_thumb_click(i))

            # Filename label
            name_label = ctk.CTkLabel(
                frame, text=f["filename"][:16],
                font=ctk.CTkFont(size=9), text_color="gray"
            )
            name_label.pack()

            self.thumb_widgets.append((frame, label, f["path"]))

        # Load actual thumbnails in background
        self._load_batch(0, 12)

    def _load_batch(self, start, batch_size):
        """Load a batch of thumbnails using thread pool."""
        end = min(start + batch_size, len(self.photo_files))
        if start >= end:
            return

        paths = [(i, self.photo_files[i]["path"]) for i in range(start, end)]

        def load_one(idx_path):
            idx, path = idx_path
            try:
                img = Image.open(path)
                img.thumbnail((THUMB_SIZE, THUMB_SIZE), Image.Resampling.LANCZOS)
                return idx, img
            except Exception:
                return idx, None

        def on_loaded(future):
            try:
                results = future.result()
            except Exception:
                return
            self.after(0, lambda: self._apply_thumbs(results, end, batch_size))

        future = self.executor.submit(lambda: [load_one(p) for p in paths])
        future.add_done_callback(on_loaded)

    def _apply_thumbs(self, results, next_start, batch_size):
        """Apply loaded thumbnails to the grid on the main thread."""
        for idx, img in results:
            if img is None or idx >= len(self.thumb_widgets):
                continue
            photo = ImageTk.PhotoImage(img)
            self.thumb_cache[idx] = photo  # prevent GC
            frame, label, path = self.thumb_widgets[idx]
            label.configure(image=photo)

        # Load next batch
        if next_start < len(self.photo_files):
            self.after(50, lambda: self._load_batch(next_start, batch_size))

    def _on_thumb_click(self, idx):
        """Handle thumbnail click — show EXIF info."""
        # Deselect previous
        if self.selected_thumb_idx is not None and self.selected_thumb_idx < len(self.thumb_widgets):
            prev_frame = self.thumb_widgets[self.selected_thumb_idx][0]
            prev_frame.configure(border_width=0)

        self.selected_thumb_idx = idx
        frame, label, filepath = self.thumb_widgets[idx]
        frame.configure(border_width=2, border_color="#3B82F6")

        # Load EXIF in background
        self.exif_text.configure(state="normal")
        self.exif_text.delete("1.0", "end")
        self.exif_text.insert("end", "Loading EXIF...")
        self.exif_text.configure(state="disabled")

        def load_exif():
            info = _read_exif_detailed(filepath)
            self.after(0, lambda: self._display_exif(info, filepath))

        threading.Thread(target=load_exif, daemon=True).start()

    def _display_exif(self, info, filepath):
        """Display EXIF info in the panel."""
        self.exif_text.configure(state="normal")
        self.exif_text.delete("1.0", "end")

        self.exif_text.insert("end", f"{os.path.basename(filepath)}\n")
        self.exif_text.insert("end", "\u2500" * 30 + "\n\n")

        # Display order
        display_keys = [
            "Camera", "Platform", "Date", "GPS", "Altitude",
            "Alt (AGL)", "Alt (Abs)", "Gimbal Pitch", "Gimbal Yaw", "Gimbal Roll",
            "Sequence", "Resolution", "File Size",
        ]

        for key in display_keys:
            if key in info:
                self.exif_text.insert("end", f"{key}: {info[key]}\n")

        # Show any remaining keys not in display order
        shown = set(display_keys) | {"Make", "_lat", "_lon"}
        for key, val in info.items():
            if key not in shown:
                self.exif_text.insert("end", f"{key}: {val}\n")

        self.exif_text.configure(state="disabled")

        # Enable/disable map button
        if "_lat" in info and "_lon" in info:
            self._map_coords = (info["_lat"], info["_lon"])
            self.map_btn.configure(state="normal")
        else:
            self._map_coords = None
            self.map_btn.configure(state="disabled")

    def _open_map(self):
        """Open GPS coordinates in default browser map."""
        if hasattr(self, "_map_coords") and self._map_coords:
            lat, lon = self._map_coords
            import webbrowser
            webbrowser.open(f"https://www.google.com/maps?q={lat},{lon}")

    # ── MISSION TABLE ────────────────────────────────────────────────────────

    def _add_mission_row(self):
        row_frame = ctk.CTkFrame(self.missions_container, fg_color="transparent")
        row_frame.pack(fill="x", pady=1)

        mission_num = ctk.StringVar(value=str(len(self.missions) + 1))
        package_type = ctk.StringVar(value=PACKAGE_TYPES[0])
        date_var = ctk.StringVar(value=datetime.now().strftime("%Y%m%d"))
        seq_start = ctk.StringVar(value="1")
        seq_end = ctk.StringVar()

        ctk.CTkEntry(row_frame, textvariable=mission_num, width=50).pack(side="left", padx=2)
        ctk.CTkOptionMenu(
            row_frame, variable=package_type, values=PACKAGE_TYPES, width=180
        ).pack(side="left", padx=2)
        ctk.CTkEntry(row_frame, textvariable=date_var, width=100).pack(side="left", padx=2)
        ctk.CTkEntry(row_frame, textvariable=seq_start, width=80).pack(side="left", padx=2)
        ctk.CTkEntry(row_frame, textvariable=seq_end, width=80).pack(side="left", padx=2)

        # Color indicator
        color_idx = len(self.missions) % len(MISSION_COLORS)
        color_label = ctk.CTkLabel(row_frame, text="\u2588", text_color=MISSION_COLORS[color_idx], width=20)
        color_label.pack(side="left", padx=5)

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

    def _auto_detect_missions(self):
        """Auto-detect mission boundaries from timestamp gaps."""
        if not self.scanned_files:
            return

        # Get files with timestamps
        ts_files = [f for f in self.scanned_files if f.get("timestamp")]

        if not ts_files:
            # Fall back to sequence-only: treat all files as one mission
            seqs = sorted(f["sequence"] for f in self.scanned_files if f["sequence"])
            if seqs:
                self._clear_mission_rows()
                self._add_mission_row()
                m = self.missions[0]
                m["seq_start"].set(str(seqs[0]))
                m["seq_end"].set(str(seqs[-1]))
                self.status_var.set("Auto-detect: 1 mission (no timestamps available)")
            return

        # Sort by timestamp and split on gaps
        ts_files.sort(key=lambda f: f["timestamp"])
        groups = [[ts_files[0]]]

        for f in ts_files[1:]:
            gap = (f["timestamp"] - groups[-1][-1]["timestamp"]).total_seconds() / 60
            if gap > MISSION_GAP_MINUTES:
                groups.append([f])
            else:
                groups[-1].append(f)

        # Clear existing rows and create new ones
        self._clear_mission_rows()

        for i, group in enumerate(groups):
            seqs = sorted(f["sequence"] for f in group)
            self._add_mission_row()
            m = self.missions[i]
            m["mission_num"].set(str(i + 1))
            m["seq_start"].set(str(seqs[0]))
            m["seq_end"].set(str(seqs[-1]))

            # Use date from first file in group
            dt = group[0]["timestamp"]
            m["date"].set(dt.strftime("%Y%m%d"))

        self.status_var.set(f"Auto-detect: {len(groups)} mission(s) found")
        self._update_thumb_borders()

    def _clear_mission_rows(self):
        """Remove all mission rows."""
        for m in self.missions:
            m["frame"].destroy()
        self.missions.clear()

    def _update_thumb_borders(self):
        """Color-code thumbnail borders based on mission assignment."""
        if not self.missions or not self.thumb_widgets:
            return

        # Build sequence -> mission color map
        seq_color = {}
        for i, m in enumerate(self.missions):
            try:
                start = int(m["seq_start"].get())
                end = int(m["seq_end"].get())
                color = MISSION_COLORS[i % len(MISSION_COLORS)]
                for s in range(start, end + 1):
                    seq_color[s] = color
            except (ValueError, TypeError):
                continue

        # Apply to thumbnails
        for idx, (frame, label, path) in enumerate(self.thumb_widgets):
            if idx < len(self.photo_files):
                seq = self.photo_files[idx]["sequence"]
                color = seq_color.get(seq)
                if color:
                    frame.configure(border_width=2, border_color=color)
                else:
                    frame.configure(border_width=0)

    # ── INGEST ───────────────────────────────────────────────────────────────

    def _validate(self):
        """Validate inputs. Returns (missions_config, error_msg)."""
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
        if self.ingest_running:
            return

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

        self.ingest_running = True
        self.start_btn.configure(state="disabled")
        self.progress_bar.set(0)
        self.status_var.set("Starting ingest...")

        # Run subprocess in background thread with line-by-line progress
        threading.Thread(
            target=self._run_ingest, args=(cmd, temp_json, len(missions_config)),
            daemon=True
        ).start()

    def _run_ingest(self, cmd, temp_json, num_missions):
        """Run ingest subprocess and parse stdout for progress."""
        try:
            process = subprocess.Popen(
                cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, cwd=str(SCRIPT_DIR), bufsize=1
            )

            output_lines = []
            missions_done = 0

            for line in iter(process.stdout.readline, ""):
                line = line.rstrip()
                output_lines.append(line)

                # Parse progress from ingest_sorter output
                if "Mission:" in line:
                    self.after(0, lambda l=line: self.status_var.set(l.split("]")[-1].strip() if "]" in l else l))
                elif "Copied:" in line or "[DRY RUN]" in line:
                    missions_done += 0.5  # approximate
                    progress = min(missions_done / max(num_missions, 1), 1.0)
                    self.after(0, lambda p=progress: self.progress_bar.set(p))
                elif "Ingest complete" in line:
                    self.after(0, lambda: self.progress_bar.set(1.0))

            process.wait()

            # Clean up temp file
            try:
                temp_json.unlink()
            except OSError:
                pass

            # Report result on main thread
            output_text = "\n".join(output_lines[-30:])  # last 30 lines
            if process.returncode == 0:
                self.after(0, lambda: self._ingest_done(True, output_text))
            else:
                self.after(0, lambda: self._ingest_done(False, output_text))

        except Exception as e:
            self.after(0, lambda: self._ingest_done(False, str(e)))

    def _ingest_done(self, success, output):
        """Handle ingest completion on main thread."""
        self.ingest_running = False
        self.start_btn.configure(state="normal")

        if success:
            self.progress_bar.set(1.0)
            self.status_var.set("Ingest complete!")
            messagebox.showinfo("Success", f"Ingest complete!\n\n{output[-500:]}")
        else:
            self.status_var.set("Ingest failed.")
            messagebox.showerror("Ingest Failed", f"{output[-500:]}")

    # ── CLEANUP ──────────────────────────────────────────────────────────────

    def destroy(self):
        self.executor.shutdown(wait=False)
        super().destroy()


# ─── MAIN ────────────────────────────────────────────────────────────────────


def main():
    app = SentinelPhotoLoader()
    app.mainloop()


if __name__ == "__main__":
    main()

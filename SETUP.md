# QGIS for Sentinel Aerial - Setup Index

Two parallel QGIS capabilities plus a standalone learning path, set up on this
machine on **2026-07-09**.

- **Deliverable 1 - Interactive QGIS-MCP** (learning + prototyping): drive QGIS
  from Claude Desktop.
- **Deliverable 2 - Headless production automation** (`qgis/`): GUI-free VARI
  vegetation analysis wired to NodeODM output. **Smoke-tested and working.**
- **Deliverable 3 - Learn QGIS Independently** (`LEARN_QGIS.md`): a 60-90 min
  hands-on path using QGIS Desktop directly.

## Verified environment (2026-07-09)

| Thing | State |
|-------|-------|
| QGIS | **3.44.12 LTR** (+3.44.11) at `C:\Program Files\QGIS 3.44.12`; `qgis_process-qgis-ltr.bat` runs (GDAL 3.13.1, Py 3.12.13) |
| UV | **0.10.8** at `...\Python312\Scripts\uv.exe` |
| Python (host) | 3.12.10 |
| WSL2 | Ubuntu running |
| NodeODM | **live** at `localhost:3000` (v2.2.4) |
| Claude Desktop config | `%APPDATA%\Claude\claude_desktop_config.json` (had `square` only) |

---

## Deliverable 1 - Interactive QGIS-MCP

**Recommended server: `jjsantos01/qgis_mcp`** (the original, BlenderMCP-derived).
Why it over `nkarasiak/qgis-mcp` **for a learner**: it is the reference
implementation with by far the most tutorials/blog coverage you'll find while
learning; its clone-and-run layout lets you *read the server code* as a learning
artifact; and its smaller tool surface (add layers, run algorithms, execute
PyQGIS, render maps) is less overwhelming while you're new to both QGIS and MCP.
`nkarasiak/qgis-mcp` is the **power-user upgrade** - 102 tools (feature editing,
layout/atlas authoring, SQL), actively released (v0.6.1 on 2026-07-09), installed
via `uvx` with no clone. Switch to it later by swapping the one config block
(command `uvx`, args `--from https://github.com/nkarasiak/qgis-mcp/archive/refs/heads/main.zip qgis-mcp-server`).

### DONE automatically
- Cloned `jjsantos01/qgis_mcp` -> `C:\Users\redle.SOULAAN\Documents\qgis_mcp`
- Created its UV env (`uv sync`): `mcp==1.3.0` installed, import verified
- Verified the exact launch (`uv run --directory src/qgis_mcp ...`) resolves
- Copied the companion plugin -> `...\QGIS3\profiles\default\python\plugins\qgis_mcp_plugin\`
  (the `python\plugins` dir did not exist yet; created it)
- **Backed up** the Claude Desktop config -> `claude_desktop_config.json.bak-20260709-153324`
- **Added** the `qgis` MCP server entry (absolute `uv.exe` path so a
  GUI-launched Claude Desktop finds it regardless of PATH); JSON re-validated

The entry now in the config:
```json
"qgis": {
  "command": "C:\\Users\\redle.SOULAAN\\AppData\\Local\\Programs\\Python\\Python312\\Scripts\\uv.exe",
  "args": [
    "--directory",
    "C:\\Users\\redle.SOULAAN\\Documents\\qgis_mcp\\src\\qgis_mcp",
    "run",
    "qgis_mcp_server.py"
  ]
}
```

### ADAM MUST DO THIS (GUI / restart - cannot be automated headlessly)
1. **Open QGIS Desktop.** Menu **Plugins -> Manage and Install Plugins ->
   Installed** tab -> tick **"QGIS MCP"** to enable it. (The plugin files are
   already copied; you only need to enable it.)
2. **Start its socket server:** menu **Plugins -> QGIS MCP -> QGIS MCP** ->
   click **Start Server** (listens on `localhost:9876`). Leave QGIS open.
3. **Fully restart Claude Desktop** (Quit from the tray, not just close the
   window) so it reloads the config and starts the `qgis` MCP server.
4. **First test prompt** in Claude Desktop:
   > "Using the qgis tools, tell me the QGIS version and then add the raster at
   > `C:\Users\redle.SOULAAN\Documents\drone-pipeline\qgis\sample\sample_ortho.tif`
   > and zoom to it."

   You should see the layer appear in the open QGIS window. If Claude reports it
   can't reach QGIS, confirm the plugin's **Start Server** is running and that
   Claude Desktop was fully restarted.

---

## Deliverable 2 - Headless production automation (`qgis/`)

Full docs: **`qgis/README.md`**. Uses **VARI** (RGB-only index; NDVI is
impossible on Mini 4 Pro - no NIR).

### DONE automatically (and verified live)
- Wrote the headless analysis `qgis/rgb_vegetation_analysis.py` (VARI -> veg
  polygons -> **GeoPackage** + auto **PDF** via `QgsLayoutExporter`)
- Wrote wrappers `qgis/run_veg_analysis.bat` (Windows) and
  `qgis/run_veg_analysis.sh` (Git Bash **and** WSL -> shells to Windows QGIS)
- Wrote the NodeODM-completion trigger `qgis/veg_watch.py` (filesystem watcher)
- Wrote `qgis/make_sample_ortho.py` and **ran a full smoke test** on QGIS
  3.44.12:
  - VARI computed, **2 polygons** flagged (63.6 m2 @ VARI 0.53; 15.9 m2 @ 0.42),
    a sub-2 m2 speck correctly filtered
  - `vegetation.gpkg` (EPSG:32618, real attrs), `vegetation.pdf` (1.2 MB),
    `vegetation.tif`, `summary.json` all produced. **Exit 0.**
- Added `qgis/sample/` and `qgis/out/` to `.gitignore`

### ADAM MUST DO THIS
1. **Run it against a real mission** (first live ortho):
   ```bat
   cd C:\Users\redle.SOULAAN\Documents\drone-pipeline\qgis
   run_veg_analysis.bat "I:\My Drive\Drone Facility Plans\<mission>\odm_orthophoto.tif" ".\out_<mission>" ZV-XXXX
   ```
   (No real mission ortho was reachable from this session - `I:` Google Drive
   returned empty/online-only - so live-mission verification is yours to run.)
2. **Wire the trigger** (pick one):
   - **n8n Execute Command node** after the ortho-download step (snippet in
     `qgis/README.md`), **or**
   - register `veg_watch.py` as a **Scheduled Task** (logon trigger) pointed at
     your ortho output folder.
3. Optional: tune `--threshold` / `--min-area` after eyeballing the first real
   PDF (dense canopy may want a higher threshold).

### Could not verify
- A `.model3` Processing model was **not** shipped (hand-authored model JSON
  can only be validated in the GUI). The single PyQGIS script is the reliable
  artifact; build the `.model3` yourself via `LEARN_QGIS.md` step 5 if you want
  one. The algorithm chain and `qgis_process` CLI equivalents are in
  `qgis/README.md`.

---

## Deliverable 3 - Learn QGIS Independently

Full guide: **`LEARN_QGIS.md`**. A self-guided 60-90 min path (load raster +
vector, symbolize, attribute table, Processing algorithm, Graphical Modeler,
Print Layout -> PDF) using your own drone/parcel data, mapped to your BCCC /
ArcGIS Pro concepts. Includes how to use the Deliverable-1 MCP as a learning aid.

### DONE automatically
- Wrote `LEARN_QGIS.md` with a synthetic sample ortho already on disk to use
  (`qgis/sample/sample_ortho.tif`)

### ADAM MUST DO THIS
- Work through steps 1-6 in QGIS Desktop at your own pace (needs the GUI).

---

## Rollback / safety notes
- Claude Desktop config backup: `%APPDATA%\Claude\claude_desktop_config.json.bak-20260709-153324`
  (restore by copying it back over the live file if the `qgis` entry ever misbehaves).
- No secrets were written to the repo. Repo `.env` remains git-ignored.
- The `qgis_mcp` clone lives **outside** this repo (`Documents\qgis_mcp`) so it
  is not committed here.

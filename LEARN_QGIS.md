# Learn QGIS Independently - 60-90 min Hands-On Quickstart

Deliverable 3. This is a **standalone** path to learn QGIS Desktop the software,
decoupled from the drone pipeline. It complements your BCCC *Intro-to-GIS*
(ArcGIS Pro) course by teaching you the free-tool equivalents so you build muscle
memory in both. Nothing here depends on the automation in `qgis/`.

**You already have:** QGIS 3.44.12 LTR installed (`C:\Program Files\QGIS 3.44.12`).
Open **"QGIS Desktop 3.44.12"** from the Start menu.

**Sample data you own** (pick whichever is handy):

- A drone orthophoto - any `odm_orthophoto.tif` from a past mission, or the
  synthetic test ortho already on disk:
  `C:\Users\redle.SOULAAN\Documents\drone-pipeline\qgis\sample\sample_ortho.tif`
- A parcel / fence vector layer - a parcel GeoJSON/SHP from a mission, or export
  one from `parcel_lookup.py`. If you have none handy, QGIS can digitize one in
  step 3.

---

## 1. Load a raster + a vector layer (10 min)

1. **Layer -> Add Layer -> Add Raster Layer** -> pick your ortho `.tif` -> **Add**.
   The imagery draws in the canvas. Note the CRS shown bottom-right (the sample
   is EPSG:32618, UTM 18N).
2. **Layer -> Add Layer -> Add Vector Layer** -> pick a parcel/fence file -> **Add**.
   (Skip if you have none; you'll create one in step 3.)
3. In the **Layers** panel (left), drag layers to reorder. Vector on top of
   raster. Right-click a layer -> **Zoom to Layer** to frame it.

**Concept:** QGIS is layer-based like ArcGIS Pro's Contents pane. The topmost
layer draws last (on top).

## 2. Symbolize (10 min)

1. Double-click the vector layer -> **Symbology** tab.
2. Switch the dropdown from *Single Symbol* to **Categorized** (or *Graduated*
   for a numeric field). Pick a field (e.g. a parcel class), click **Classify**,
   choose a color ramp, **Apply**.
3. Set fill to ~50% opacity so the ortho shows through: click the symbol ->
   **Opacity** slider.
4. For the raster: double-click it -> **Symbology** -> if it's single-band you can
   apply a color ramp; for RGB imagery leave it as *Multiband color*.

**Concept:** Symbology = how attribute values map to colors/sizes. This is the
same idea as ArcGIS Pro's Symbology pane.

## 3. The attribute table (10 min)

1. Right-click the vector layer -> **Open Attribute Table**.
2. Toggle **Edit** (pencil icon). Add a field with the **New Field** button
   (e.g. `note`, text). Type a value in a cell. Toggle edit off -> **Save**.
3. Use the **Select Features by Expression** (epsilon icon) -> try
   `"area_m2" > 50` (or any numeric field). Selected rows highlight on the map.
4. **Field Calculator** (abacus icon): create/Update a field, e.g.
   `area_calc = $area` to compute geometry area into an attribute.

**Concept:** Every vector feature has a row of attributes. `$area`, `$length`,
`$geometry` are QGIS expression variables (ArcGIS calls these geometry tokens).

## 4. Run a Processing algorithm from the Toolbox (15 min)

1. **Processing -> Toolbox** (or `Ctrl+Alt+T`). A searchable tree of ~1000
   algorithms appears.
2. Search **"buffer"** -> **Vector geometry -> Buffer**. Input = your fence/parcel
   layer, Distance = e.g. `5` (map units = meters in UTM), **Run**. A buffered
   layer is added - useful for encroachment/setback zones.
3. Try a raster one: search **"raster calculator"** -> **Raster analysis ->
   Raster calculator** and compute a simple band expression on the ortho.

**Concept:** The Processing Toolbox is the heart of QGIS analysis. Every tool
here is also callable headlessly as `qgis_process run <provider>:<alg>` - which
is exactly how the pipeline automation in `qgis/` runs with no GUI.

## 5. Build a small model in the Graphical Modeler (15 min)

This is the visual version of the vegetation pipeline - a great way to *see* the
`qgis/` automation as a diagram.

1. **Processing -> Graphical Modeler** (opens a blank canvas).
2. **Inputs** panel -> drag **Raster Layer** onto the canvas (name it `ortho`).
3. **Algorithms** panel -> search **"raster calculator"**, drag it in, set the
   expression to VARI-style `(B-A)/(B+A-C)` using the ortho bands, output ->
   *model output* named `vari`.
4. Add **Reclassify by table** or **Raster calculator** to threshold `> 0.15`,
   then **Polygonize (raster to vector)**, then **Extract by expression**
   (`$area > 2`). Chain each algorithm's output into the next.
5. **Save** the model (`.model3`). Now **Run** it once from the modeler.

**Concept:** A model chains algorithms into a reusable tool. Export it and it
runs headless via `qgis_process run model:<name>`. This is literally the
algorithm chain listed in `qgis/README.md` - build it here and you understand the
automation end-to-end.

## 6. Export a Print Layout to PDF (10 min)

1. **Project -> New Print Layout** -> name it. The layout designer opens.
2. **Add Item -> Add Map** -> drag a rectangle; it shows your canvas view. Use
   **Item Properties -> Set to map canvas extent**.
3. **Add Item -> Add Legend**, **Add Scale Bar**, **Add Label** (a title).
4. **Layout -> Export as PDF**. Done - a client-ready map.

**Concept:** This is the GUI version of `QgsLayoutExporter` that the headless
script drives automatically. Do it once by hand and the automated PDF makes sense.

---

## Use the QGIS-MCP as a learning aid

Once Deliverable 1 is wired up (see `SETUP.md`), you can drive QGIS from Claude
Desktop and then **inspect what it did in the GUI** - a fast feedback loop:

- Ask Claude: *"In QGIS, add the raster at `...sample_ortho.tif` and zoom to it."*
  Then watch the layer appear and check its properties yourself.
- Ask: *"Run a 5-meter buffer on the fence layer and symbolize it red."* Then
  open **Symbology** to see exactly which settings it changed.
- Ask: *"Open the attribute table and select features where area_m2 > 50."* Then
  confirm the selection and read the expression it used.

Learn by *asking for the outcome*, then *reverse-engineering the clicks* it
implies. Because the MCP calls the same Processing algorithms you use manually,
whatever Claude does maps 1:1 to a menu path you can repeat by hand.

---

## Where this fits vs. BCCC / ArcGIS Pro

| BCCC / ArcGIS Pro concept | QGIS free-tool equivalent (this guide) |
|---------------------------|----------------------------------------|
| Contents pane | Layers panel (step 1) |
| Symbology pane | Symbology tab (step 2) |
| Attribute table + Field Calculator | Same names (step 3) |
| Geoprocessing tools | Processing Toolbox (step 4) |
| ModelBuilder | Graphical Modeler (step 5) |
| Layout view | Print Layout (step 6) |
| AGOL (Wk4 gap) | Not covered here - use QField/Mergin per your crosswalk |

Do steps 1-6 once and you can navigate QGIS confidently for both the course and
Sentinel deliverables.

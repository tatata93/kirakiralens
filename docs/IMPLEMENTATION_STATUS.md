# Implementation Status

Updated: 2026-08-13

## Working milestone

KiraKiraLens currently delivers a runnable Phase 1 plus the catalog foundation
from Phase 2.

Verified working:

- Native PySide6 desktop application on Windows.
- Diagram-first editor with spherical, conic, and even-asphere profiles,
  selection, zoom, pan, aperture-stop marker, image plane, traced paraxial rays,
  and editable gap/BFL dimensions.
- Full-frame / infinity / 50 mm / F4 / Pentax K target preset with editable EFL,
  F-number, BFL, and maximum diameter controls.
- Initial custom triplet whose Optiland result is EFL 50.000 mm and BFL 45.460 mm.
- A persistent editor directly above the diagram exposes surface type, radius,
  conic constant, even-asphere coefficients, thickness/gap, material, clear and
  outer diameter, coating, comment, variable locks, and stop assignment.
- Diagram operations for inserting, duplicating, deleting, reversing, and
  customizing elements and surfaces. Air gaps are selectable and draggable.
- Non-blocking context menus for surfaces, elements, and gaps. The synchronized
  surface table remains available as an optional hidden-by-default dock.
- Correct reversal of singlets and cemented doublets, including radius signs,
  media order, thickness order, and surface coatings.
- Catalog part immutability and conversion to a custom copy.
- Versioned `.kklens` ZIP container containing strict, human-readable JSON.
- Optiland 0.5.9 runs in a persistent child process. Edits are debounced and only
  the latest pending design is analyzed, keeping the GUI responsive during the
  roughly eight-second engine call.
- Catalog filters for manufacturer, text, shape, material, coating, diameter,
  clear aperture, EFL, power sign, wavelength, and photographic relevance.

## Edmund catalog result

Ten supplied Excel workbooks are preserved under `data/source/edmund/`.

- Total products: 920
- Fully designable products: 918
- Incomplete but browsable: 2
- Rejected rows: 0
- Duplicate part numbers: 0
- Distinct verified material names: 21
- Material names successfully resolved by Optiland: 21

Parts `67-332` and `67-333` lack complete R1/R2/R3 and CT1/CT2 data in the source
workbook. They are deliberately not designable. See
`data/generated/edmund_import_report.json` for hashes and details.

## Main code locations

- `src/kirakiralens/domain.py`: persistent optical domain model and reversal.
- `src/kirakiralens/catalog/edmund.py`: read-only Excel normalization.
- `src/kirakiralens/catalog/database.py`: SQLite schema and catalog queries.
- `src/kirakiralens/optics/optiland_adapter.py`: pinned Optiland 0.5.9 boundary.
- `src/kirakiralens/optics/analysis_process.py`: isolated Optiland worker process.
- `src/kirakiralens/optics/paraxial.py`: ray paths using indices returned by Optiland.
- `src/kirakiralens/ui/analysis_controller.py`: debouncing and process lifecycle.
- `src/kirakiralens/ui/diagram_editor.py`: diagram selection property editor.
- `src/kirakiralens/ui/lens_view.py`: interactive lens cross-section.
- `src/kirakiralens/ui/main_window.py`: desktop workspace and background analysis.
- `tests/`: domain, import, persistence, Optiland, and UI smoke tests.

## Verification

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m kirakiralens
```

The current suite has ten passing tests. A Windows-rendered 1500 x 900 capture
is stored at `docs/images/main-window.png` and has been checked for text clipping
and incoherent overlap.

## Known limitations and next phase

The next work should be Phase 3: constrained continuous optimization.

Not yet implemented:

- Merit-function editor and adjustable metric weights.
- Optimization of unlocked gaps, stop position, and custom curvatures.
- Search duration, pause/cancel/checkpoints, and candidate comparison.
- Triplet, Tessar, and Double Gauss catalog searches.
- Free-topology discrete-continuous search.
- Spot, MTF, PSF, distortion, and relative-illumination analysis views.
- `.seq`, `.len`, and `.zmx` exchange.
- Vendor web collectors, price history, and stock tracking.
- User-created preset persistence beyond the built-in editable preset.

The aperture stop may be assigned to any modeled surface. A surface inserted in
an air region acts as a transparent dummy surface and can therefore carry a
floating stop. The editor currently targets rotationally symmetric sequential
refractive systems; tilted, decentered, coordinate-break, diffractive, and
freeform surfaces are outside the current photographic-lens model.

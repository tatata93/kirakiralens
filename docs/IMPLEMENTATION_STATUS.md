# Implementation Status

Updated: 2026-08-13

## Working milestone

KiraKiraLens currently delivers a runnable Phase 1 plus the catalog foundation
from Phase 2.

Verified working:

- Native PySide6 desktop application on Windows.
- Diagram-first editor with real spherical profiles, selection, zoom, pan,
  aperture-stop marker, image plane, traced paraxial rays, and BFL dimension.
- Full-frame / infinity / 50 mm / F4 / Pentax K target preset with editable EFL,
  F-number, BFL, and maximum diameter controls.
- Initial custom triplet whose Optiland result is EFL 50.000 mm and BFL 45.460 mm.
- Surface selection from the diagram and exact editing in the inspector.
- Synchronized secondary surface table.
- Gap context menu for inserting a selected catalog lens or custom singlet.
- Correct reversal of singlets and cemented doublets, including radius signs,
  media order, thickness order, and surface coatings.
- Catalog part immutability and conversion to a custom copy.
- Versioned `.kklens` ZIP container containing strict, human-readable JSON.
- Background Optiland 0.5.9 first-order analysis so the GUI remains responsive.
- Catalog filters for text, shape, material, and maximum outer diameter.

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
- `src/kirakiralens/optics/paraxial.py`: ray paths using indices returned by Optiland.
- `src/kirakiralens/ui/lens_view.py`: interactive lens cross-section.
- `src/kirakiralens/ui/main_window.py`: desktop workspace and background analysis.
- `tests/`: domain, import, persistence, Optiland, and UI smoke tests.

## Verification

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m kirakiralens
```

The current suite has eight passing tests. A Windows-rendered 1500 x 900 capture
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

The present stop model attaches the stop to the rear surface of a selected
element. A freely floating stop in an air gap belongs in Phase 3. Only sequential
spherical refractive systems are exposed in the UI at this milestone.

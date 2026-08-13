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
- The IMAGE plane is directly clickable. Its modeless editor includes common
  sensor presets and custom width/height, finite/infinite object distance,
  image distance and lock, sensor-derived or arbitrary field angles, field
  weights, F/d/C and other wavelength presets, wavelength weights, primary
  wavelength, and ray/curve sampling counts.
- Horizontal, vertical, and diagonal angle of view appear in first-order and
  performance results; every performance field carries its actual half-angle.
- Initial custom triplet whose Optiland result is EFL 50.000 mm and BFL 45.460 mm.
- After a prescription change, the unlocked image plane automatically follows
  Optiland's paraxial focus. Manual BFL entry or an image-distance lock switches
  the design to manual image positioning.
- A persistent editor directly above the diagram exposes surface type, radius,
  conic constant, even-asphere coefficients, thickness/gap, material, clear and
  outer diameter, coating, comment, variable locks, and stop assignment.
- Diagram operations for inserting, duplicating, deleting, reversing, and
  customizing elements and surfaces. A dedicated insertion target exists before
  L1, and every air gap/BFL has an in-diagram numeric spin box as well as drag.
- Non-blocking context menus for surfaces, elements, and gaps. The synchronized
  surface table remains available as an optional hidden-by-default dock and
  edits every object, lens, and image row, including both sides of every lens,
  materials, apertures, aspheres, comments, stop assignment, and locks.
- Undo and redo cover prescription, insertion/deletion, spacing, image-plane,
  and ray-setting edits.
- Correct reversal of singlets and cemented doublets, including radius signs,
  media order, thickness order, and surface coatings.
- Catalog part immutability and conversion to a custom copy.
- Versioned `.kklens` ZIP container containing strict, human-readable JSON.
- Optiland 0.5.9 runs in persistent child processes. Startup performs no optical
  calculation. Edits are debounced, non-optical edits do not trigger analysis,
  and unchanged prescriptions reuse bounded in-memory caches.
- A modeless performance window calculates and plots weighted polychromatic
  MTF, spot diagrams, transverse and longitudinal aberration, field curvature,
  astigmatism, and distortion. Stable merit metrics are stored for optimization.
- Element diameter and per-surface clear aperture are hard radial apertures in
  Optiland real-ray tracing.
- Catalog filters for manufacturer, text, shape, material, coating, diameter,
  clear aperture, EFL, power sign, wavelength, and photographic relevance.
- A dedicated automatic-design window runs cancellable, budgeted mixed
  optimization. It accepts numeric EFL/tolerance, image F-number, and
  target/minimum/range BFL conditions plus an optional maximum total track;
  EFL, BFL, and total track can be required constraints.
  Its discrete stage searches catalog replacements, orientation, and order with
  a bounded beam, then passes the best prescription to Optiland/SciPy continuous
  optimization of unlocked custom radii/thicknesses, air gaps, and image plane.
- Classical-form mode creates catalog-only Cooke Triplet, Tessar, and six-
  singlet Double Gauss approximations from explicit component-count, power,
  shape, and stop-adjacency rules. It does not depend on the current design's
  element count.
- Up to 50 retained candidates are compared in a dedicated tab. Selecting a row
  updates a read-only lens layout and bill of materials; any selected candidate
  can be applied. The top configured candidates receive additional weighted
  polychromatic MTF screening at 40 lp/mm.

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
- `src/kirakiralens/optics/performance.py`: numerical performance analyses and merit metrics.
- `src/kirakiralens/optics/performance_process.py`: isolated performance worker.
- `src/kirakiralens/optics/automatic_design.py`: locks, variables, normalized merit, and optimization.
- `src/kirakiralens/optics/discrete_search.py`: catalog substitution, orientation, and order beam search.
- `src/kirakiralens/optics/classic_forms.py`: Triplet, Tessar, and Double Gauss template rules and seed construction.
- `src/kirakiralens/optics/automatic_design_process.py`: isolated optimization worker.
- `src/kirakiralens/optics/paraxial.py`: ray paths using indices returned by Optiland.
- `src/kirakiralens/ui/analysis_controller.py`: debouncing and process lifecycle.
- `src/kirakiralens/ui/diagram_editor.py`: diagram selection property editor.
- `src/kirakiralens/ui/lens_view.py`: interactive lens cross-section.
- `src/kirakiralens/ui/main_window.py`: desktop workspace and background analysis.
- `src/kirakiralens/ui/performance_window.py`: modeless analysis controls and plots.
- `src/kirakiralens/ui/system_settings_window.py`: image, field, wavelength, and ray settings.
- `src/kirakiralens/ui/automatic_design_window.py`: optimization budget, merit weights, and results.
- `tests/`: domain, import, persistence, Optiland, and UI smoke tests.

## Verification

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m kirakiralens
```

The current suite has twenty-six passing tests. A Windows-rendered 1500 x 900 capture
is stored at `docs/images/main-window.png` and has been checked for text clipping
and incoherent overlap.

## Known limitations and next phase

The next work should finish Phase 3 and expand Phase 4's discrete catalog search.

Not yet implemented:

- Hard limits for image-quality metrics beyond EFL/BFL, floating stop-position
  optimization, checkpoints, pause, and Pareto-front selection.
- Element-count-changing free-topology discrete-continuous search.
- PSF, relative-illumination, through-focus, and tolerance analysis views.
- `.seq`, `.len`, and `.zmx` exchange.
- Vendor web collectors, price history, and stock tracking.
- User-created preset persistence beyond the built-in editable preset.

The aperture stop may be assigned to any modeled surface. A surface inserted in
an air region acts as a transparent dummy surface and can therefore carry a
floating stop. The editor currently targets rotationally symmetric sequential
refractive systems; tilted, decentered, coordinate-break, diffractive, and
freeform surfaces are outside the current photographic-lens model.

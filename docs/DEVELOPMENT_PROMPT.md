# KiraKiraLens Development Prompt

## Role and objective

You are a senior engineer experienced in photographic lens design, Optiland,
numerical optimization, Python, and desktop GUI development.

Build KiraKiraLens in this repository:
https://github.com/tatata93/kirakiralens.git

KiraKiraLens is a desktop application for designing photographic lenses by
combining commercially available singlets and cemented lens assemblies. It must
also support manually entered custom optical prescriptions. Use Optiland as the
optical calculation engine and PySide6 as the preferred desktop UI framework.

Never inspect or modify `C:\Users\tak01\github\kougaku`.

## Initial design preset

Provide the following built-in preset:

- Sensor: 36 x 24 mm full frame
- Object distance: infinity
- Effective focal length: 50 mm
- F-number: F/4
- Mount label: Pentax K
- Back focal length target: 45.46 mm
- Sensor cover glass: none

Every value must be editable. Users must be able to create, duplicate, rename,
save, and delete presets. Do not hard-code the application around the initial
preset.

Back focal length is defined in this application as the axial distance from the
vertex of the final refracting surface to the image plane. It must support an
exact fixed value, a minimum/maximum range, or a weighted target with tolerance.
Display it as a dimension in the lens layout. No camera mirror-clearance or
mount-interference model is required initially.

## Primary interaction model

The lens cross-section is the main design UI. The traditional surface table is a
secondary precision editor and must remain synchronized bidirectionally with the
diagram.

The diagram must support:

- Zooming, panning, selection highlighting, undo, and redo.
- Clicking a surface to edit radius/curvature, geometry, material transition,
  clear aperture, coating, bounds, and lock state.
- Clicking an air space to edit separation, bounds, and lock state.
- Right-clicking between components to insert a singlet, cemented assembly,
  aperture stop, air space, or dummy surface.
- Replacing, duplicating, deleting, reversing, locking, and converting a catalog
  component into a custom component.
- Displaying traced rays, the aperture stop, image plane, element dimensions,
  and back focal length.
- Editing exact values in a side inspector without cluttering the diagram.

Reversing an element must correctly reverse the surface order and transform
radius signs, material transitions, surface-specific coatings, and thicknesses.
A cemented assembly must reverse as one catalog component unless the user
explicitly converts and separates it.

## Supported optical components

Support catalog and custom versions of at least:

- Plano-convex and plano-concave singlets
- Bi-convex and bi-concave singlets
- Positive and negative meniscus singlets
- Cemented achromatic doublets
- Other cemented doublets and cemented triplets when catalog data is available

Do not limit materials to N-BK7. Support photographic lens materials available
in manufacturer data, including crown, flint, low-dispersion, high-index, fused
silica, and other catalog glasses supported by Optiland or a verified custom
dispersion model. Never infer an unknown glass from focal length or refractive
index alone. Mark missing data explicitly and allow such parts to be excluded.

## Diameter and aperture constraints

Distinguish physical outer diameter from optical clear aperture throughout the
data model, UI, ray tracing, and search.

- Set a global maximum component diameter for a design.
- Set an exact diameter or minimum/maximum diameter independently for every
  singlet or cemented assembly.
- Lock or unlock custom-component outer diameter and clear aperture separately.
- Treat catalog outer diameter and clear aperture as immutable catalog values.
- Exclude catalog parts that violate a per-component or global hard limit.
- Allow diameter goals to be hard constraints or weighted objectives.
- Store an assembly outer diameter and per-surface clear apertures for cemented
  components.
- Apply clear apertures during ray tracing and evaluate clipping, vignetting,
  relative illumination, and image-circle coverage.
- Select the rim of a component in the diagram to edit and display diameter
  constraints and locks.
- Show maximum system diameter and every component diameter in candidate
  comparisons.

For example, the user must be able to require element 1 to be 25-30 mm, element
2 to be no larger than 20 mm, and the final element to be exactly 12.5 mm.

## Catalog database

Use a normalized SQLite database. Do not assume one product always consists of
one glass and two surfaces. Represent at least this hierarchy:

1. Manufacturer and catalog product
2. Optical component or cemented assembly
3. Ordered optical surfaces
4. Media and axial thicknesses between surfaces
5. Time-dependent commercial data such as price and stock
6. Provenance records

Store, where available:

- Manufacturer, part number, product family, product type, and shape class
- Surface order, geometry, radius, conic/aspheric data, clear aperture, and coating
- Medium/glass, center thickness, cement layer, and dispersion data
- Outer diameter, edge thickness, effective focal length, and back focal length
- Design wavelength, usable wavelength range, centering and dimensional tolerances
- Price, currency, stock status, and discontinued status
- Source URL, source file, source row, retrieval time, and confidence/status

Users must be able to browse and filter by manufacturer, part number, shape,
component type, material, focal length, diameter, coating, wavelength range,
price, and availability. A design or search may allow only selected products,
shapes, or manufacturers.

Custom components can be registered in the database. Their manufacturer may be
`Custom` or empty, and their part number may be empty or an automatically
generated identifier. Preserve a link to the source catalog part when a custom
component was created by editing a catalog part.

## Catalog data ingestion

The first source will be an Edmund Optics Excel workbook supplied by the user.
Preserve the original workbook unchanged. Build an import workflow that:

1. Detects sheets, headers, units, merged cells, and product-family differences.
2. Shows a reviewable mapping from source columns to normalized fields.
3. Validates units, signs, required fields, duplicate part numbers, and glass names.
4. Produces the normalized SQLite database and a documented UTF-8 CSV export.
5. Produces an import report listing accepted, incomplete, rejected, and duplicate
   records with reasons.
6. Preserves source file, sheet, row, URL if present, and import timestamp.

After the Edmund importer works, collect publicly available data from official
vendor product pages, CSV/Excel downloads, and PDF catalogs and build a separate,
testable importer for each vendor. Respect access restrictions and site terms.
Do not fabricate unavailable specifications. Keep price and stock history
separate from stable optical prescription data.

## Design modes

Provide three design modes that share the same editor, constraints, evaluation,
and locking system.

### Manual design

Create a system from catalog components or manually entered surfaces. Support
radius, thickness, material, diameter, clear aperture, spacing, stop, and image
plane editing from both the diagram and surface table.

### Classical-form search

Provide topology templates for at least Cooke triplet, Tessar, and Double Gauss.
Templates describe structural rules and starting topology, not a fixed
prescription. Search catalog components, orientation, spacing, and stop position
while preserving the selected family rules. Allow later addition of more
templates.

### Free-topology search

Within user limits, explore component count, catalog part number, ordering,
orientation, air gaps, stop position, and image-plane position without requiring
a classical family. Support searches restricted by selected products, vendors,
types, shapes, materials, diameter, price, and availability.

Do not attempt an unbounded Cartesian exhaustive search. Use staged candidate
filtering and appropriate discrete methods such as beam search, evolutionary
algorithms, or MCMC, followed by Optiland continuous optimization.

## Mixed discrete-continuous optimization

Treat these as discrete variables for catalog designs:

- Catalog part number
- Component count and topology
- Component order
- Front/back orientation
- Stop location between components

Treat these as continuous variables when unlocked:

- Air gaps
- Stop axial position
- Image-plane position
- Custom lens curvature, thickness, diameter, and clear aperture

Catalog radii, materials, cemented structure, thicknesses, diameters, and clear
apertures are immutable. Generate discrete candidates first, then optimize their
continuous variables with Optiland. Cache repeated calculations where safe and
make all randomized searches reproducible with an explicit seed.

## Locks, bounds, and constraints

Locking is a shared capability, not a separate design mode. Independently lock:

- Catalog part or custom component identity
- Component count, order, and orientation
- Individual surface curvature and material
- Center thickness and air gap
- Outer diameter and clear aperture
- Stop location and size
- Image-plane position and back focal length

An unlocked value may have lower and upper bounds. Locks and hard constraints
must never be violated. Targets with tolerances and weights are soft constraints.
Reject or heavily penalize invalid ray traces, surface intersections, negative
thicknesses, component collisions, impossible apertures, and total-internal-
reflection failures inappropriate for the intended imaging path.

## Analysis and merit function

Evaluate the center, intermediate field positions, full-frame edges, and corners
at configurable wavelengths and field sampling. Include, where applicable:

- Effective focal length, F-number, back focal length, total track, and image circle
- RMS/geometric spot size and encircled energy
- MTF and PSF
- Spherical aberration, coma, astigmatism, and field curvature
- Longitudinal and lateral chromatic aberration
- Distortion, vignetting, and relative illumination
- Price, estimated weight, component count, maximum diameter, and total length

Each metric must have an enable switch, goal, tolerance, hard-limit option, and
adjustable weight. Normalize metrics before combining them so units and numeric
scale do not let one metric dominate accidentally. Provide editable merit
presets such as Balanced, Resolution, Low Distortion, Compact/Lightweight, and
Low Cost. Present multiple Pareto candidates instead of hiding all tradeoffs in
one score.

## Search budget and execution

Let the user set search duration in seconds, minutes, hours, or unlimited. Also
support candidate limit, generation limit, worker count, and random seed.
Optimization must run outside the GUI thread and support progress display,
cancel, pause, resume where technically reliable, and periodic checkpointing.
When the budget expires, return and preserve the best valid candidates found so
far. Never report an invalid or untraced candidate as the best result.

## Project and exchange formats

Use a versioned `.kklens` container as the native format. It should be a ZIP
container with human-readable JSON plus any embedded catalog snapshots and
search/checkpoint metadata required to reproduce the design. Keep the saved
domain model independent from live Optiland Python objects and convert through a
tested adapter layer.

Support import/export through Optiland for Code V `.seq`, OSLO `.len`, and Zemax
`.zmx` as capabilities permit. Prioritize and test Code V `.seq` exchange with
OpTaliX. Direct `.otx` support is a later feature and must not be claimed until a
round-trip test with OpTaliX proves prescription equivalence. Report unsupported
features and conversion losses instead of silently discarding them.

## Architecture

Separate at least these responsibilities:

- PySide6 presentation and interaction layer
- Framework-independent optical domain model
- Optiland adapter and analysis service
- Merit-function and constraint system
- Discrete candidate generator and continuous optimizer
- SQLite catalog repository and vendor importers
- Project persistence and exchange-format adapters
- Background job control and checkpointing

Pin the Optiland version. Keep an explicit compatibility layer so an Optiland API
change does not corrupt project files or spread throughout the UI.

## Delivery phases

### Phase 1: Manual optical editor

Build the desktop shell, diagram-first editor, synchronized surface table,
inspector, presets, project save/load, Optiland conversion, ray trace, and basic
analysis. The initial full-frame 50 mm F/4 Pentax K preset must work.

### Phase 2: Catalog foundation

Build the Edmund Excel importer, normalized SQLite database, CSV export and
reporting, catalog browser, insertion/replacement, correct component reversal,
custom-component registration, and diameter filtering.

### Phase 3: Constrained continuous optimization

Implement locks, bounds, weighted merit configuration, search budgets,
background execution, checkpoints, result comparison, and continuous
optimization of valid unlocked variables.

### Phase 4: Classical catalog search

Implement Triplet, Tessar, and Double Gauss templates, mixed candidate search,
bill of materials, Pareto comparison, and tested `.seq` exchange.

### Phase 5: Free-topology search

Implement constrained free topology, scalable discrete-continuous search,
additional vendor importers, and optional GPU acceleration after profiling.

## Verification and completion rules

Keep the application runnable after each phase. Never use dummy values to claim
that optical analysis or optimization is complete. Add automated tests for:

- Domain-model and Optiland round trips
- Known lens prescriptions and first-order properties
- Save/load reproducibility and schema migration
- Singlet and cemented-assembly reversal
- Catalog immutability and custom-copy behavior
- Diameter and clear-aperture clipping
- Locks, bounds, hard constraints, and time-budget termination
- Invalid candidate rejection
- Excel normalization and provenance retention
- `.seq` import/export round trips and conversion-loss reporting
- Critical diagram editing workflows

At the start of any implementation task, inspect the repository and this file,
write or update a concise implementation plan, identify the current delivery
phase, and implement the smallest complete vertical increment. Document optical
sign conventions, units, coordinate systems, and any assumptions before relying
on them in persisted data.

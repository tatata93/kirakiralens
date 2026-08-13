# Automatic Design

Updated: 2026-08-13

KiraKiraLens implements a mixed catalog-discrete and continuous optimization
pipeline. It runs in a separate process, has time and evaluation budgets,
reports progress, can be cancelled, preserves the best valid point found, and
does not modify the design until the user applies that result.

The user enters an effective focal length and tolerance, image F-number, a BFL
condition, and an optional maximum total track. BFL can be unconstrained, a
target with tolerance, a minimum, or a range. Effective focal length, BFL, and
total track may be marked required; a result outside a required condition is
rejected instead of merely receiving a low ranking.

## Merit function

The optimizer uses Optiland real-ray operands with explicit normalization:

- effective focal length error divided by its user-entered tolerance;
- final-surface-to-image distance error divided by the configured BFL tolerance;
- RMS spot radius at every configured field and wavelength divided by the
  primary-wavelength Airy radius;
- chief-ray image-height error divided by a 2% distortion scale.
- excess total track divided by its normalization tolerance.

The field and wavelength weights configured in the image/ray window are
normalized before use. The four merit groups have independent adjustable
weights. A failed ray trace receives a large penalty and cannot become the best
result.

F-number is passed to Optiland as the image-space F-number aperture definition.
It therefore defines the ray bundle for every merit evaluation rather than
being treated as another soft merit term.

This is not a universal photographic-lens pass/fail score. A useful design must
still be inspected in the performance window for tangential/sagittal MTF at
10/20/40 lp/mm, chromatic behavior, field curvature, distortion, ray clipping,
and construction constraints. Numerical goals depend on sensor sampling,
intended rendering, manufacturing tolerance, and cost.

## Variables and locks

The current implementation can vary:

- unlocked spherical radii on custom components;
- unlocked internal thicknesses on custom components;
- unlocked air gaps, including gaps adjacent to catalog components;
- image-plane position when enabled and unlocked.

Catalog radii, glass, cemented structure, internal thickness, diameter, and
clear aperture remain immutable. Surface, element, gap, and image-plane locks
are hard exclusions. Bounds are conservative and positive gaps/thicknesses are
maintained.

Local search uses SciPy Powell and global search uses differential evolution;
both evaluate Optiland's optical model. Local search is the normal first choice.

## Catalog-discrete stage

The discrete mode builds a filtered catalog candidate pool for each existing
lens position. It uses a seeded, bounded beam search over three operations:

- replace an unlocked position with a compatible catalog component;
- reverse an orientation-unlocked singlet or cemented component;
- swap two element-unlocked positions while retaining the air-gap state at
  each axial position.

Candidates are deduplicated by their complete optical-analysis signature and
are scored with coarse multi-field, multi-wavelength real-ray spot metrics,
EFL, BFL, and optional distortion. The best discrete prescription becomes the
starting point for the regular continuous optimization of unlocked air gaps and
custom prescription variables. Catalog prescriptions themselves are never
continuously deformed.

The highest-ranked discrete candidates receive an additional weighted
polychromatic 40 lp/mm MTF screening. The application retains up to 50 ranked
candidates and shows score, constraint state, EFL, F-number, BFL, RMS spot,
MTF40, distortion, total track, layout, and bill of materials. The first row is
the continuously optimized best discrete candidate; remaining rows are clearly
marked as coarse discrete evaluations and can also be applied to the editor.

When the optimizer varies the image plane, the accepted result is switched to
manual image positioning so the editor's ordinary paraxial auto-focus does not
overwrite the optimized real-ray focus.

## Classical forms

Classical-form mode replaces the current element count with a selected form and
constructs a catalog pool for every constrained position:

- Cooke Triplet: positive singlet / negative singlet / positive singlet;
- Tessar: positive singlet / negative singlet / positive cemented achromatic
  doublet, giving four glass lenses in three components;
- Double Gauss: positive / positive / negative, stop, negative / positive /
  positive, implemented as six catalog singlets.

The form rules constrain component count, power sign, catalog shape, and the
surface adjacent to the nominal stop. Reordering is disabled in this mode,
while orientation reversal remains searchable. The Tessar and Double Gauss
forms are off-the-shelf approximations of their historical forms, not replicas
of a particular patented prescription. The ordinary discrete mode remains
available for unconstrained replacement within the current element count.

## Research basis

Optiland's optimization framework defines weighted operands, bounded radius and
thickness variables, RMS-spot operands, focal-length operands, and local/global
optimizers. Its case study progresses from paraxial/Seidel control to
multi-field, multi-wavelength RMS spot optimization.

Microsoft Research's Lens Factory treats off-the-shelf lens design as a mixed
discrete-continuous problem. It optimizes continuous air gaps, uses spot/optical
path metrics before MTF when the starting design is poor, then performs a
separate discrete stage for component combinations. KiraKiraLens retains that
separation while using its own bounded beam search suitable for an interactive
desktop application.

Optiland's image solve moves the image surface to paraxial focus. The editor's
automatic image tracking uses the same paraxial-focus principle after a lens
prescription changes, unless the image distance is manually fixed or locked.

Patent literature likewise treats lens optimization as multi-objective. For
example, US20090002835A1 discusses re-optimizing a lens merit function while
trading MTF, lateral chromatic aberration, distortion, and electronic
correction. It is not used as a numerical acceptance threshold here; it supports
keeping the merit terms separately weighted and exposing the tradeoff to the
user.

Primary references:

- [Optiland optimization framework](https://optiland.readthedocs.io/en/latest/developers_guide/optimization_framework.html)
- [Optiland RMS spot optimization](https://optiland.readthedocs.io/en/stable/gallery/optimization/rms_spot_size.html)
- [Optiland optimization case study](https://optiland.readthedocs.io/en/latest/examples/Tutorial_5c_Optimization_Case_Study.html)
- [Optiland analysis framework](https://optiland.readthedocs.io/en/stable/developers_guide/analysis_framework.html)
- [Optiland quick start and image solve](https://optiland.readthedocs.io/en/latest/quickstart.html)
- [Optiland image F-number aperture](https://optiland.readthedocs.io/en/latest/_modules/optiland/aperture/image_fno.html)
- [Lens Factory: Automatic Lens Generation Using Off-the-shelf Components](https://www.microsoft.com/en-us/research/publication/lens-factory-automatic-lens-generation-using-off-shelf-components/)
- [US540132A: Cooke Triplet photographic lens](https://patents.google.com/patent/US540132A/en)
- [US721240A: Rudolph four-lens photographic objective](https://patents.google.com/patent/US721240A/en)
- [US20050185301A1: Modified Double Gauss photographic objective](https://patents.google.com/patent/US20050185301A1/en)
- [US20090002835A1: Method for lens performance optimization using electronic aberration correction](https://patents.google.com/patent/US20090002835)

## Deliberate limits

Not yet implemented:

- automatic element-count changes and unrestricted topology generation;
- floating stop-location search, Pareto-front selection, checkpoints, and
  pause/resume;
- MTF as a late-stage optimization operand;
- manufacturing tolerance, relative illumination, and cost objectives.

Those belong to the discrete and tolerance stages and must not silently change
catalog prescriptions.

# Automatic Design

Updated: 2026-08-13

KiraKiraLens implements a mixed catalog-discrete and continuous optimization
pipeline. It runs in a separate process, has time and evaluation budgets,
reports progress, can be cancelled, preserves the best valid point found, and
does not modify the design until the user applies that result.

The user enters an effective focal length and tolerance, image F-number, and a
BFL condition. BFL can be unconstrained, a target with tolerance, a minimum, or
a range. Effective focal length and BFL may independently be marked required;
a result outside a required condition is rejected instead of merely receiving
a low ranking.

## Merit function

The optimizer uses Optiland real-ray operands with explicit normalization:

- effective focal length error divided by its user-entered tolerance;
- final-surface-to-image distance error divided by the configured BFL tolerance;
- RMS spot radius at every configured field and wavelength divided by the
  primary-wavelength Airy radius;
- chief-ray image-height error divided by a 2% distortion scale.

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

When the optimizer varies the image plane, the accepted result is switched to
manual image positioning so the editor's ordinary paraxial auto-focus does not
overwrite the optimized real-ray focus.

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
- [US20090002835A1: Method for lens performance optimization using electronic aberration correction](https://patents.google.com/patent/US20090002835)

## Deliberate limits

Not yet implemented:

- automatic element-count changes and unrestricted topology generation;
- Triplet, Tessar, and Double Gauss topology rules;
- stop-location search, Pareto candidate comparison, checkpoints, pause/resume;
- MTF as a late-stage optimization operand;
- manufacturing tolerance, relative illumination, and cost objectives.

Those belong to the discrete and tolerance stages and must not silently change
catalog prescriptions.

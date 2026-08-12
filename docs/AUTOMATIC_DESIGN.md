# Automatic Design

Updated: 2026-08-13

KiraKiraLens currently implements constrained continuous optimization of the
prescription already shown in the diagram. It runs in a separate process, has
time and evaluation budgets, reports progress, can be cancelled, preserves the
best valid point found, and does not modify the design until the user applies
that result.

## Merit function

The optimizer uses Optiland real-ray operands with explicit normalization:

- effective focal length error divided by the target focal length;
- final-surface-to-image distance error divided by the configured BFL tolerance;
- RMS spot radius at every configured field and wavelength divided by the
  primary-wavelength Airy radius;
- chief-ray image-height error divided by a 2% distortion scale.

The field and wavelength weights configured in the image/ray window are
normalized before use. The four merit groups have independent adjustable
weights. A failed ray trace receives a large penalty and cannot become the best
result.

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
- image-plane position when explicitly enabled and unlocked.

Catalog radii, glass, cemented structure, internal thickness, diameter, and
clear aperture remain immutable. Surface, element, gap, and image-plane locks
are hard exclusions. Bounds are conservative and positive gaps/thicknesses are
maintained.

Local search uses SciPy Powell and global search uses differential evolution;
both evaluate Optiland's optical model. Local search is the normal first choice.

## Research basis

Optiland's optimization framework defines weighted operands, bounded radius and
thickness variables, RMS-spot operands, focal-length operands, and local/global
optimizers. Its case study progresses from paraxial/Seidel control to
multi-field, multi-wavelength RMS spot optimization.

Microsoft Research's Lens Factory treats off-the-shelf lens design as a mixed
discrete-continuous problem. It optimizes continuous air gaps, uses spot/optical
path metrics before MTF when the starting design is poor, then performs a
separate discrete stage for component combinations. That separation is retained
here: the implemented window is the continuous stage, not a claim of catalog
combination search.

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
- [Lens Factory: Automatic Lens Generation Using Off-the-shelf Components](https://www.microsoft.com/en-us/research/publication/lens-factory-automatic-lens-generation-using-off-shelf-components/)
- [US20090002835A1: Method for lens performance optimization using electronic aberration correction](https://patents.google.com/patent/US20090002835)

## Deliberate limits

Not yet implemented:

- automatic catalog part choice, order, count, or orientation;
- Triplet, Tessar, and Double Gauss topology rules;
- stop-location search, Pareto candidate comparison, checkpoints, pause/resume;
- MTF as a late-stage optimization operand;
- manufacturing tolerance, relative illumination, and cost objectives.

Those belong to the discrete and tolerance stages and must not silently change
catalog prescriptions.

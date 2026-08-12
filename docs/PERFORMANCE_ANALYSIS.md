# Performance Analysis

Updated: 2026-08-13

KiraKiraLens evaluates the current sequential prescription with real rays in a
separate Optiland process. Opening a project or the performance window does not
start this calculation. A run occurs only when the user presses `解析実行`, and
an unchanged design with unchanged analysis settings reuses the previous result.

## Implemented analyses

Field plots use either configurable fractions of the selected sensor's diagonal
field or user-entered half-angles. Every field label includes its actual angle.
The default spectral samples are Fraunhofer F, d, and C lines at 0.48613,
0.58756, and 0.65627 µm. Wavelength and field weights are editable.

- **MTF versus spatial frequency:** tangential and sagittal curves in lp/mm,
  with explicit values at 10, 20, and 40 lp/mm. The implementation forms the
  complex geometric OTF from image-plane ray coordinates for each wavelength,
  multiplies it by the circular-aperture diffraction transfer, then combines
  the complex OTFs before taking the modulus. Lateral color is therefore not
  discarded by independently centering every wavelength.
- **Spot diagram:** wavelength-colored image-plane ray intersections in µm,
  centered on the primary-wavelength centroid. RMS radius and 80% geometric
  encircled radius are stored, and the primary-wavelength Airy radius is drawn
  as a reference.
- **Transverse ray aberration:** tangential and sagittal image-plane ray error
  in µm against normalized pupil coordinate for every field and wavelength.
  RMS and peak-to-valley values are retained for optimization.
- **Longitudinal aberration:** axial intersection displacement in mm against
  normalized pupil coordinate. A common d-line paraxial reference preserves
  both longitudinal spherical aberration and axial chromatic aberration.
- **Field curvature and astigmatism:** tangential and sagittal focus shift in mm
  over normalized field, calculated by Optiland's parabasal-ray analysis.
- **Distortion:** f-tan distortion in percent over normalized field for every
  wavelength.
- **Image geometry:** the result stores and displays horizontal, vertical, and
  diagonal angle of view calculated from the configured sensor and actual EFL.

The result dictionary contains a `summary.merit_metrics` section with stable
keys for the future optimizer: `mtf40_min`, `corner_rms_spot_um`,
`max_ray_fan_rms_um`, `edge_distortion_percent`, `edge_astigmatism_mm`,
`primary_longitudinal_spherical_um`, and `axial_color_um`.

## Why these metrics

MTF combines contrast and spatial resolution and is conventionally separated
into tangential and sagittal response across image height. ZEISS publishes
camera-lens MTF at 10, 20, and 40 cycles/mm, while Edmund describes center,
70%-field, and full-field T/S curves. Spot and ray-fan plots remain necessary
because one MTF score does not reveal which aberration or pupil zone is causing
the loss. Field curvature, astigmatism, distortion, and chromatic focus shifts
then expose the principal off-axis and color tradeoffs needed by an optimizer.

ISO 12233 specifies measured spatial-frequency response for a complete digital
camera. KiraKiraLens instead predicts lens performance from a nominal optical
prescription; its MTF must not be presented as an ISO 12233 camera measurement.

Primary references:

- [Optiland analysis framework](https://optiland.readthedocs.io/en/stable/developers_guide/analysis_framework.html)
- [Optiland SpotDiagram API](https://optiland.readthedocs.io/en/stable/api/analysis/analysis.spot_diagram.html)
- [Optiland ThroughFocusMTF API](https://optiland.readthedocs.io/en/stable/api/analysis/analysis.through_focus_mtf.html)
- [ISO 12233:2024 abstract](https://www.iso.org/standard/88626.html)
- [Edmund Optics: Modulation Transfer Function](https://www.edmundoptics.com/knowledge-center/application-notes/imaging/modulation-transfer-function-mtf-and-mtf-curves/)
- [ZEISS Dimension 2/35 MTF data sheet](https://www.zeiss.com/content/dam/consumer-products/downloads/industrial-lenses/datasheets/en/dimension-lenses/datasheet-zeiss-dimension-235.pdf)

## Current limits

- Wavelength weights are relative user inputs; illuminant spectra and sensor
  quantum-efficiency curves are not yet imported automatically.
- The MTF is a nominal hybrid geometric-diffraction prediction. Manufacturing
  tolerances, decenter, tilt, flare, scattering, sensor stack, and sampling are
  not included.
- Coating text is persisted but is not yet converted into wavelength-dependent
  coating models. Clear aperture and element outer diameter are applied as hard
  radial apertures during Optiland tracing.
- PSF, relative illumination, through-focus MTF, and tolerance Monte Carlo are
  valuable later additions, but they are not substituted with placeholder data.

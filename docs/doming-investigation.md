# Doming investigation (COPR dataset, 2026-08-07)

Luke noticed extreme terrain tilt in both COPR Godot scenes. This documents the
controlled investigation. Conclusion up front: **the tilt is self-calibration
doming, it is an information limit of the capture (single nadir grid, unknown
compact camera, no GPS), and no solver setting fixes it.** GCPs anchor pose
(~1–1.7 m horizontal in every run) but cannot reshape a calibration-bent model.

## Evidence chain

1. **z=0 hypothesis falsified.** All dataset GCP elevations are 0.0
   (placeholders). USGS 3DEP shows the ten targets span only 0.56 m (flat
   terrace ~3 m NAVD88) — missing heights explain the below-sea-level offset,
   not the tilt.
2. **Systematic ramp.** Vertical residuals in every run form a monotonic
   SE→NW gradient (−3 m → +4 m over ~50 m), regardless of who tagged or how
   many tags. That is a shape error, not a georeferencing error.
3. **Self-calibration instability (smoking gun).** Same 41 images, three runs,
   three cameras: focal 1.145 / 1.188 / 1.374 (20% spread), k3 flips sign.
   The imagery cannot determine the lens; the solver trades lens error against
   a smooth terrain bow (projective compensation, James & Robson 2014 pattern).
4. **Constraint saturation test** (`copr-3dep`): best possible ground truth —
   37 tags, 10 points, two independent taggers, real 3DEP heights. Ramp
   unchanged (−3.0 → +4.2 m). ~37 GCP observations cannot outvote ~300k
   self-consistent tie-point observations in bundle adjustment.
5. **Fixed-calibration test** (`copr-fixedcam`, `use-fixed-camera-params`):
   ramp attenuated at NW (+4.2→+2.1), worsened at SE (−3.0→−3.9), LE90
   3.65→2.93 m. Zero-distortion EXIF defaults are also a wrong lens model.
   Confirms: the problem is not *which* calibration strategy, but that this
   imagery cannot support any correct one.

## Capture doctrine (the actual fix — applies to all our own flights)

- **Cross-grid flight lines** (two perpendicular passes minimum).
- **Oblique images mixed in** (~30–45° tilt on some passes) — breaks the
  nadir degeneracy that lets the lens model absorb error.
- **RTK GCPs with real ellipsoidal heights** — cannot prevent doming, but
  exposes it immediately in checkpoint residuals.
- **One-time checkerboard calibration per camera**, passed to ODM as known
  fixed calibration — removes self-cal wander without pretending zero
  distortion.

## Side findings

- `gcp04`'s published pixel tags are internally inconsistent (3–7 m ray-miss);
  hand re-tagging the same marker gave 0.16 m residual. Dataset defect.
- `gcp06`'s *surveyed coordinate* is ~3.7–4.1 m off per three independent tag
  sets. Dataset defect; worth reporting upstream to odm_data_copr.
- Method: checkpoint grading + ray-miss consistency implemented in
  `scripts/gcp_residuals.py` (ODM has no native GCP holdout).

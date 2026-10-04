# Validation record — v1.1.0

Validation performed on **3 October 2026** using Python **3.12.14**, Linux x86-64 and the pinned runtime in `requirements.txt` / `constraints.txt`. A clean virtual environment containing only runtime/test dependencies was used for final integration and browser checks. `pip check` reported no dependency conflicts. The actual dashboard was rendered and inspected at desktop and mobile widths.

## Automated integration suite

**20 Python tests passed.** These use real OpenCV codecs, the bundled ONNX model, FastAPI requests, WebSockets and SQLite persistence.

- Unauthenticated access, credentials, login Origin, CSRF enforcement and viewer role permissions.
- Actual video upload, sampled analysis, completion, four replay image views, summary, CSV/JSON exports and reference-aware deletion.
- Invalid codecs/extensions, upload limits, missing media and settings validation.
- Polygon save/read, coordinate bounds, negative frames and YOLO dataset ZIP contents.
- Neural bus detection and a nonrectangular instance mask with nonzero area; detection-only mode omits masks.
- Model checksum rejection.
- Tracker association, timestamps, occlusion, velocity and ID expiry.
- Explicit proximity-and-motion grouping behavior.
- Live JPEG WebSocket ingestion, pause/resume/stop and recorded-frame replay.
- JPEG dimensions/header validation.
- Restart recovery marks unfinished runs interrupted.
- Update WebSocket returns the final persisted file state.
- Global assignment avoids the greedy-assignment failure and preserves IDs through crossing/class flicker.
- Optical-flow motion against known independently moving vehicle pixels, plus known camera pan: 170 raw px/s, 140 camera-relative px/s, stationary background-relative object.
- One-time FFmpeg browser conversion, authenticated byte-range streaming (206), timeline bounds, timestamp order and cache deletion.
- Client camera capture timestamps remain intact through real binary WebSockets.
- Older settings receive new defaults while preserving saved values.
- Latest-frame snapshots return while the inference lock is held.
- Real bundled-model segmentation/tracking on the independent-motion bus demo: 40 observations, stable bus ID, nonzero contours, expected ~71.25 analysis px/s.

The test runner emits one upstream Starlette deprecation warning about the httpx TestClient adapter; the tests pass. This concerns test tooling and is not a runtime inference error.

## Actual browser workflow

An actual Chromium 131 headless browser ran the application against a spawned Uvicorn server and completed:

1. Sign-in, video upload, real ONNX segmentation and object-table updates.
2. Native video playback, synchronized overlay/mask/trail canvases and video-time seeking. The dashboard issued zero per-frame JPEG requests.
3. Analysis summary and downloading/parsing a JSON export with **15** sampled frames, including real bus masks.
4. Polygon drawing/saving and a dataset ZIP download.
5. Model checksum verification/warmup, settings save, system health and audit-log reads.
6. Browser camera capture using Chromium's synthetic camera, real binary WebSockets, JPEG decode, actual ONNX inference, pause/resume/stop.
7. Responsive layout at **1600 px** and **390 px** width with no page-level horizontal overflow and no unexpected JavaScript errors.

The synthetic camera check validates transport and workflow. It is not a claim that a physical camera or drone adapter was tested. `tests/e2e.cjs` contains the optional browser test; install Playwright and a compatible Chromium browser separately to rerun it. Set `PYTHON_EXECUTABLE` for the runtime interpreter if it is outside the project's `.venv`.

```bash
# Optional developer browser test, after local runtime setup:
npm install --no-save playwright
npx playwright install chromium
node tests/e2e.cjs
```

## Slow-processing playback regression

`tests/smooth_playback.cjs` starts a test-only server that adds **450 ms** to each actual ONNX prediction. It uploads a 12-second, 15 FPS video, runs genuine segmentation and measures decoded browser presentation timestamps. The production entry point has no artificial latency.

| Measurement | Observed result on this Linux host |
|---|---:|
| Mean inference time including injected delay | 553.54 ms |
| Browser observation interval | 3.502 s |
| Video clock advancement | 3.502 s |
| Largest gap between presented video frames | 0.066667 s (15 FPS source cadence) |
| Dropped video frames | 0 |
| JPEG frame requests during playback | 0 |
| Analyzed observations over the 12-second source | 16 (adaptive sampling) |

The normal browser test separately delayed timeline requests by 700 ms; the video advanced 1.11 seconds during its 1.1-second check. `tests/renderer.mjs` passes source-time interpolation, learned contour transformation, immutable source observations, bounded prediction and stale-overlay hiding checks.

The machine and browser determine achievable playback FPS. These results demonstrate that slow inference no longer blocks decoding on this host; they are not a guarantee for every device, codec or camera. Reports are in `performance-results.json` and screenshots show actual browser output.

```bash
# Optional Node developer checks (Python runtime must already be installed):
node tests/renderer.mjs
node tests/e2e.cjs
node tests/smooth_playback.cjs
```

## Model decoder parity

The v1.0.0 decoder check used the original Ultralytics bus example image. On that image, the custom ONNX decoder was compared with the original `.pt` model using Ultralytics, square 640 input, `rect=False`, `retina_masks=True`, confidence 0.30 and NMS IoU 0.50.

| Check | Measured value |
|---|---:|
| Bus confidence | 0.86125 |
| Maximum bounding-box coordinate difference | approximately 0.0044 px |
| Confidence difference | approximately 0.0000032 |
| Reconstructed mask IoU with original model output | approximately 0.99904 |

v1.1.0 additionally compares the new batched OpenCV projection with the previous NumPy projection on this same image; see `mask-projection-parity.json`. The mask regression remains part of the current suite.

This is a **one-image decoder consistency check**, not an accuracy result or a test-set mAP. It verifies that the runtime interprets the actual learned mask outputs correctly. No target-domain vehicle ground truth or new training experiment was available.

## Checks still required on your deployment

Docker/Compose, HTTPS proxy integration, Windows/macOS launchers, physical cameras, actual drone imagery, long-duration streaming, multi-user load and trained custom models have not been field-validated here. Their implementations and setup instructions are included. Validate these on your intended host and collect independent labeled footage before making operational performance or accuracy claims.


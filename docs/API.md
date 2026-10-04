# API

REST endpoints require an authenticated `mt_session` cookie except health/login. Mutating endpoints additionally require `X-CSRF-Token`, returned by login/me. The dashboard handles both. Administrators can retrieve the OpenAPI schema at `/api/openapi.json` (other authenticated roles can also inspect it).

| Method | Endpoint | Purpose |
|---|---|---|
| GET | `/api/health` | Public healthcheck |
| POST / GET / POST | `/api/auth/login`, `/api/auth/me`, `/api/auth/logout` | Sign in, session, sign out |
| GET / POST / DELETE | `/api/users`, `/api/users`, `/api/users/{id}` | Admin: list, create, revoke access |
| GET / PUT | `/api/settings` | Read/update defaults (update: admin) |
| GET | `/api/models` | Registered model provenance and availability |
| POST | `/api/models/{id}/verify` | Verify checksum and warm up inference |
| GET / POST | `/api/media` | List/upload videos |
| GET | `/api/media/{id}/frame.jpg?frame_index=0` | Source-frame preview |
| GET | `/api/media/{id}/playback` | Preparation status/progress; starts preparation on demand |
| GET | `/api/media/{id}/video` | Authenticated browser MP4, HTTP Range supported; 409 until ready |
| DELETE | `/api/media/{id}` | Delete unreferenced media |
| GET / POST | `/api/jobs` | List/create analysis sessions |
| GET / DELETE | `/api/jobs/{id}` | Session details/delete finished session |
| POST | `/api/jobs/{id}/control` | `{ "action": "pause" / "resume" / "stop" }` |
| GET | `/api/jobs/{id}/result?seq=0` | Selected result; omit seq for latest |
| GET | `/api/jobs/{id}/frames/{seq}/{view}.jpg` | original, overlay, mask, trail |
| GET | `/api/jobs/{id}/timeline?at=0&ahead=8&limit=240` | Bounded source-time observation window (`at-1` through `at+ahead`) |
| GET | `/api/jobs/{id}/summary` | Measured run aggregates and downsampled chart series |
| GET | `/api/jobs/{id}/export/{json,csv}` | Full streaming exports |
| GET / PUT | `/api/media/{id}/annotations?frame_index=0` | Source-frame polygons in normalized [0,1] coordinates |
| GET | `/api/dataset/export` | Reviewed YOLO segmentation dataset ZIP |
| GET | `/api/events?level=ALL` | Recent audit events; INFO/WARN/ERROR filters |
| GET | `/api/system` | Worker, storage and runtime health |

`POST /api/jobs` accepts the settings fields plus `media_id`, `name`, `model_id`, `mode` (`segment` or `detect`) and `source` (`file` or `camera`). File jobs require uploaded media; camera jobs must omit media_id. Sampling FPS caps analyzed source frames. `analysis_size` (480–1280, default 960), `adaptive_sampling` (default true) and `compensate_camera` (default true) are supported. Adaptive sampling may lower the effective rate to reserve CPU headroom. Native playback is independent of this rate.

`GET /api/jobs/{id}/result` returns `{ "frame": null }` before the first prediction, or the persisted frame with objects, masks/contours, image motion, group heuristic and measured inference latency. CSV includes object observations only; the JSON export additionally represents frames with zero detections.

### WebSockets

- `/ws/jobs/{id}`: authenticated, read-only updates `{job, frame}`. The final state is sent and the socket closes. Frontend falls back to polling on an unexpected disconnect.
- `/ws/live/{id}`: create a camera job first. Send `{"csrf":"session-csrf"}`, wait for `{"ready":true}`, then send timestamped JPEG binary messages up to 4 MiB and 1920×1080. The new packet is 4 ASCII bytes `MTV1`, an 8-byte little-endian Float64 capture timestamp in seconds since the client session started, then JPEG bytes. Legacy raw JPEG messages remain accepted and use server elapsed time. Capture timestamps must be finite, nonnegative and increasing. Wait for each result before sending the next frame. Replies contain `{job,frame}`; a skipped/paused frame returns `frame:null`. Server also enforces the configured sampling rate.

WebSocket Origin must match `PUBLIC_ORIGIN` or the current application origin. Production Uvicorn uses a 4 MiB WebSocket message limit. Browser camera frames fit the configured analysis image size before sending. Results include raw `velocity`, optional `relative_velocity`, `motion_source`, `movement`, `camera_motion`, `sampling_fps` and pipeline/inference timings. Display interpolation never changes exported observations.


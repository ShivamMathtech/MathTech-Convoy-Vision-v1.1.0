# Troubleshooting

| Symptom | What to check |
|---|---|
| Startup asks for ADMIN_PASSWORD | On first start set a unique 12+ character password, or use the launcher prompt |
| Python launcher fails | Install Python 3.12 with its launcher/PATH option, extract the ZIP and run again |
| Model missing/checksum mismatch | Restore `models/` from the ZIP; do not rename arbitrary model files to the bundled filename |
| No detections in drone video | Lower confidence carefully, inspect object size/viewpoint, and evaluate/fine-tune on independently labeled aerial data |
| APC/Jeep/road labels absent | The model returns generic vehicle instances only; these are not classes silently inferred from the reference |
| Rectangles appear but no masks | Choose Detection + Segmentation and a segmentation model; detection-only intentionally omits masks |
| Upload rejected | Check file size, actual codec, frame count and resolution; renamed text files are not valid videos |
| MOV/H.265 cannot decode | Convert with your own FFmpeg installation: `ffmpeg -i input.mov -c:v libx264 -pix_fmt yuv420p -an output.mp4` |
| Video still shows the old sampled-image behavior | Stop the old service, apply all v1.1.0 program files, restart, hard-refresh and verify version 1.1.0 in Settings |
| Preparing smooth playback | Wait for the one-time H.264 conversion; large/unsupported videos need preparation before native playback |
| Video plays but overlays disappear temporarily | Results have not reached this playback time. Playback continues; replay the completed run, lower analysis FPS or select Low-power CPU |
| Movement still reflects old behavior | Start a new run; earlier saved results are preserved rather than rewritten |
| Entire scenery appears to move | Inspect `camera_motion.available`; reliable background features allow relative motion, otherwise values are raw image motion |
| Camera denied/unavailable | Use localhost or HTTPS; grant browser permission; close apps already using the device |
| Live camera socket cannot connect | Include the websockets dependency, proxy WebSocket upgrades, set the correct PUBLIC_ORIGIN and use one worker |
| Camera disconnected | Re-enable the preview and start a new camera analysis after stopping the previous session |
| File processing slower than source video | Choose Low-power CPU; enable adaptive sampling; lower analysis FPS; set MAX_ACTIVE_JOBS=1 and restart; inspect CPU load |
| Delete video blocked | Delete dependent saved sessions first; they need the original video for replay |
| Session interrupted after restart | Saved frames still replay; start a new run for the original video |
| Dataset validation empty | Annotate multiple independent videos and re-export; one video cannot provide an independent held-out split |
| Secure login cookie missing on localhost | Set COOKIE_SECURE=false for local HTTP; true belongs with HTTPS |
| Forgotten password | Stop the server and run `python scripts/reset_password.py --username admin` in the runtime environment |


# v1.1.0 playback and movement fix

1. Stop the application with Ctrl+C and close the old dashboard tab.
2. Keep a backup of your old project, or run `python scripts/backup.py --output backups/before-v1.1.0.zip` while stopped.
3. Extract the new ZIP separately. Copy its program files into the existing application folder. Preserve your `.env`, `data/` and `.venv/`. Do not replace your existing database with an empty folder.
4. Run `start_windows.bat` on Windows or `bash start.sh` on Linux/macOS. The launcher detects changed requirements and installs `imageio-ffmpeg` with its platform-specific FFmpeg binary. Internet is needed for this dependency installation, not for inference.
5. Open http://localhost:8000 and hard-refresh with Ctrl+Shift+R. Verify **Version 1.1.0** in Settings → System health.
6. Select your existing uploaded video. Start a **new** analysis run to obtain the improved motion measurements. Old runs retain their original exported values.
7. On a slower PC, choose **Low-power CPU**, keep Adaptive sampling enabled, and run one analysis at a time. You can set `MAX_ACTIVE_JOBS=1` in `.env` and restart.

No database schema rebuild is required. Old settings receive the new defaults without losing saved values. Video preparation happens on demand; it can take time for a large or unsupported clip. After preparation, the native browser player runs independently of model inference. Prepared videos are cache files under `data/playback/`; deleting an unreferenced media item also removes its cache. Backup intentionally omits these reproducible cache files.

The normal launcher remains the production entry point. `tests/slow_app.py` is a development fixture with artificial latency and is used only by the slow-CPU regression check.

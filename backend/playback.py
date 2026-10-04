"""Prepare browser video once. Inference and display never share a decoder lock."""
from concurrent.futures import ThreadPoolExecutor
import subprocess
import threading
import cv2
import imageio_ffmpeg
from .jobs import storage_bytes

class PlaybackStore:
    def __init__(self, db, config):
        self.db, self.config = db, config
        self.directory = config.data_dir / "playback"
        self.directory.mkdir(exist_ok=True)
        for partial in self.directory.glob("*.partial.mp4"):
            partial.unlink(missing_ok=True)
        self.lock = threading.RLock()
        self.states, self.processes = {}, {}
        self.closed = False
        self.pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="playback-prep")

    def status(self, media):
        mid = media["id"]
        source = self.config.data_dir / "uploads" / media["filename"]
        target = self.directory / (mid + ".mp4")
        with self.lock:
            if target.is_file():
                return {"status":"ready", "progress":1., "url":f"/api/media/{mid}/video", "transcoded":True}
            if mid in self.states:
                return dict(self.states[mid])
            cap = cv2.VideoCapture(str(source))
            code = int(cap.get(cv2.CAP_PROP_FOURCC)); cap.release()
            codec = "".join(chr((code >> (8*i)) & 255) for i in range(4)).lower()
            if source.suffix.lower() in {".mp4", ".m4v"} and codec in {"avc1", "h264"} and max(media["width"],media["height"]) <= 1280:
                self.states[mid] = {"status":"ready", "progress":1., "url":f"/api/media/{mid}/video", "transcoded":False}
            else:
                self.states[mid] = {"status":"queued", "progress":0.}
                self.pool.submit(self.prepare, dict(media))
            return dict(self.states[mid])

    def path(self, media):
        state = self.status(media)
        if state["status"] != "ready":
            return None
        prepared = self.directory / (media["id"] + ".mp4")
        return prepared if prepared.is_file() else self.config.data_dir / "uploads" / media["filename"]

    def prepare(self, media):
        mid = media["id"]
        temporary = self.directory / (mid + ".partial.mp4")
        target = self.directory / (mid + ".mp4")
        process = None
        try:
            with self.lock:
                if self.closed:
                    return
                self.states[mid] = {"status":"preparing", "progress":0.}
            binary = imageio_ffmpeg.get_ffmpeg_exe()
            command = [binary,"-hide_banner","-loglevel","error","-nostdin","-y",
              "-i",str(self.config.data_dir/"uploads"/media["filename"]),"-map","0:v:0","-an",
              "-vf","scale=w='min(1280,iw)':h='min(1280,ih)':force_original_aspect_ratio=decrease:force_divisible_by=2,setsar=1",
              "-c:v","libx264","-preset","ultrafast","-crf","23","-pix_fmt","yuv420p",
              "-threads","2","-movflags","+faststart","-progress","pipe:1",str(temporary)]
            process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
            with self.lock:
                self.processes[mid] = process
                if self.closed:
                    process.terminate()
            for line in process.stdout:
                if self.closed:
                    process.terminate(); break
                key, _, value = line.strip().partition("=")
                if key == "out_time_us":
                    try:
                        progress = min(.99, float(value)/1_000_000/max(.001,media["duration"]))
                    except ValueError:
                        continue
                    with self.lock:
                        self.states[mid] = {"status":"preparing", "progress":progress}
                    if storage_bytes(self.config.data_dir) > self.config.max_storage_mb*1024**2:
                        process.terminate(); raise ValueError("Playback preparation exceeded the storage quota")
            code = process.wait(timeout=30)
            if code != 0 or not temporary.is_file() or temporary.stat().st_size < 100:
                raise ValueError("Video conversion failed. Convert the clip to H.264 MP4 and upload again.")
            if storage_bytes(self.config.data_dir) > self.config.max_storage_mb*1024**2:
                raise ValueError("Playback preparation exceeded the storage quota")
            temporary.replace(target)
            with self.lock:
                self.states[mid] = {"status":"ready", "progress":1., "url":f"/api/media/{mid}/video", "transcoded":True}
        except Exception as exc:
            if process is not None and process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill(); process.wait(timeout=5)
            temporary.unlink(missing_ok=True)
            with self.lock:
                self.states[mid] = {"status":"failed", "progress":0., "error":str(exc)[:240]}
            self.db.event("Playback preparation failed: "+str(exc)[:200],"ERROR")
        finally:
            if process is not None and process.stdout is not None:
                process.stdout.close()
            with self.lock:
                self.processes.pop(mid,None)

    def delete(self, mid):
        with self.lock:
            if self.states.get(mid,{}).get("status") in {"queued","preparing"}:
                raise ValueError("Wait for video preparation to finish before deleting")
            self.states.pop(mid,None)
        (self.directory/(mid+".mp4")).unlink(missing_ok=True)

    def close(self):
        with self.lock:
            self.closed = True
            for process in self.processes.values():
                if process.poll() is None:
                    process.terminate()
        self.pool.shutdown(wait=True,cancel_futures=True)

"""Pengambil frame dari IP camera lewat RTSP (TCP) dengan OpenCV.

Satu thread latar membaca stream kamera terus-menerus dan hanya menyimpan
frame TERBARU. Banyak klien HTTP berbagi satu koneksi RTSP ke kamera, jadi
kamera tidak kewalahan. Thread berhenti sendiri saat tidak ada yang meminta
frame (IDLE_TIMEOUT) dan menyala lagi saat ada permintaan baru.
"""
import os

# Harus diset SEBELUM cv2 membuka stream pertama.
os.environ.setdefault("OPENCV_FFMPEG_CAPTURE_OPTIONS", "rtsp_transport;tcp")

import logging
import threading
import time

import cv2
from django.conf import settings

log = logging.getLogger(__name__)


class CameraReader:
    def __init__(self):
        self._cond = threading.Condition()
        self._thread = None
        self._frame = None          # frame BGR terbaru (numpy array)
        self._frame_id = 0
        self._last_access = 0.0
        self._connected = False
        self._last_error = ""
        self._jpeg_cache = (0, None)  # (frame_id, bytes)
        self._cache_lock = threading.Lock()

    # ------------------------------------------------------------------ API
    def touch(self):
        """Tandai ada klien yang aktif dan pastikan thread pembaca berjalan."""
        self._last_access = time.time()
        with self._cond:
            if self._thread is None or not self._thread.is_alive():
                self._thread = threading.Thread(
                    target=self._run, name="rtsp-reader", daemon=True
                )
                self._thread.start()

    def wait_for_frame(self, last_id, timeout=5.0):
        """Tunggu frame yang lebih baru dari last_id. Return (id, frame) atau (last_id, None)."""
        self.touch()
        deadline = time.time() + timeout
        with self._cond:
            while self._frame_id <= last_id:
                remaining = deadline - time.time()
                if remaining <= 0:
                    return last_id, None
                self._cond.wait(remaining)
            return self._frame_id, self._frame

    def encode_jpeg(self, frame_id, frame):
        """Encode ke JPEG, di-cache per frame supaya banyak klien tidak encode ulang."""
        with self._cache_lock:
            cached_id, cached = self._jpeg_cache
            if cached_id == frame_id and cached is not None:
                return cached
            ok, buf = cv2.imencode(
                ".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, settings.JPEG_QUALITY]
            )
            if not ok:
                return None
            data = buf.tobytes()
            self._jpeg_cache = (frame_id, data)
            return data

    def status(self):
        return {
            "running": bool(self._thread and self._thread.is_alive()),
            "connected": self._connected,
            "frame_id": self._frame_id,
            "last_error": self._last_error,
        }

    # ------------------------------------------------------------- internal
    def _open(self):
        cap = cv2.VideoCapture()
        # Timeout buka/baca tersedia di OpenCV >= 4.5.2; abaikan jika tidak ada.
        for prop, ms in (
            (getattr(cv2, "CAP_PROP_OPEN_TIMEOUT_MSEC", None), 8000),
            (getattr(cv2, "CAP_PROP_READ_TIMEOUT_MSEC", None), 8000),
        ):
            if prop is not None:
                cap.set(prop, ms)
        cap.open(settings.RTSP_URL, cv2.CAP_FFMPEG)
        try:
            cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        except Exception:
            pass
        return cap

    def _run(self):
        log.info("Thread pembaca RTSP dimulai")
        cap = None
        backoff = 1.0
        try:
            while time.time() - self._last_access < settings.IDLE_TIMEOUT:
                if cap is None or not cap.isOpened():
                    cap = self._open()
                    if not cap.isOpened():
                        self._connected = False
                        self._last_error = "Gagal membuka stream RTSP"
                        log.warning("%s (coba lagi %.0fs)", self._last_error, backoff)
                        time.sleep(backoff)
                        backoff = min(backoff * 2, 10.0)
                        continue
                    backoff = 1.0
                    self._connected = True
                    self._last_error = ""
                    log.info("Terhubung ke kamera")

                ok, frame = cap.read()
                if not ok or frame is None:
                    self._connected = False
                    self._last_error = "Gagal membaca frame, menyambung ulang"
                    log.warning(self._last_error)
                    cap.release()
                    cap = None
                    time.sleep(1.0)
                    continue

                if settings.FRAME_WIDTH and frame.shape[1] > settings.FRAME_WIDTH:
                    scale = settings.FRAME_WIDTH / frame.shape[1]
                    frame = cv2.resize(frame, None, fx=scale, fy=scale)

                with self._cond:
                    self._frame = frame
                    self._frame_id += 1
                    self._cond.notify_all()
        finally:
            if cap is not None:
                cap.release()
            self._connected = False
            log.info("Thread pembaca RTSP berhenti (tidak ada klien)")


_camera = None
_camera_lock = threading.Lock()


def get_camera():
    global _camera
    with _camera_lock:
        if _camera is None:
            _camera = CameraReader()
        return _camera

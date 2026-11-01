import os
import threading
import time
import logging

import cv2

from .source import SourceFailure, normalize_source, open_source, safe_release


os.environ.setdefault("OPENCV_FFMPEG_CAPTURE_OPTIONS", "rtsp_transport;tcp")
LOGGER = logging.getLogger("vigilai.capture")


DEFAULT_CONNECTION_POLICY = {
    "network_open_timeout_seconds": 8.0,
    "network_read_timeout_seconds": 5.0,
    "frame_stall_timeout_seconds": 5.0,
    "reconnect_initial_seconds": 2.0,
    "reconnect_max_seconds": 30.0,
    "reconnect_stable_seconds": 60.0,
    "webcam_retry_seconds": 10.0,
}


def _positive_number(values, key, default):
    try:
        return max(float(values.get(key, default)), 0.1)
    except (AttributeError, TypeError, ValueError):
        return float(default)


class Capture:
    """Leitura contínua de uma fonte com watchdog e reconexão escalonada."""

    def __init__(self, source, connection=None):
        self.source = source
        self.cap = None
        self.frame = None
        self.frame_id = 0
        self._last_id = 0
        self.running = True
        self.lock = threading.Lock()
        self._stop_event = threading.Event()
        self.read_interval = 0.0
        self.last_error = None
        self.backend = None
        self.connection_state = "connecting"
        self.connected_at = None
        self.last_frame_at = None
        self.next_retry_at = None
        self.reconnect_attempt = 0
        self._retry_delay = DEFAULT_CONNECTION_POLICY["reconnect_initial_seconds"]
        self.configure_connection(connection)
        self._is_webcam = isinstance(normalize_source(source), int)
        self._thread = threading.Thread(target=self._reader, daemon=True, name=f"capture-{source}")
        self._thread.start()

    def configure_connection(self, connection=None):
        """Apply advanced connection values without restarting a healthy source."""
        values = connection or {}
        self.network_open_timeout_seconds = _positive_number(
            values, "network_open_timeout_seconds", DEFAULT_CONNECTION_POLICY["network_open_timeout_seconds"]
        )
        self.network_read_timeout_seconds = _positive_number(
            values, "network_read_timeout_seconds", DEFAULT_CONNECTION_POLICY["network_read_timeout_seconds"]
        )
        self.frame_stall_timeout_seconds = _positive_number(
            values, "frame_stall_timeout_seconds", DEFAULT_CONNECTION_POLICY["frame_stall_timeout_seconds"]
        )
        self.reconnect_initial_seconds = _positive_number(
            values, "reconnect_initial_seconds", DEFAULT_CONNECTION_POLICY["reconnect_initial_seconds"]
        )
        self.reconnect_max_seconds = max(
            self.reconnect_initial_seconds,
            _positive_number(values, "reconnect_max_seconds", DEFAULT_CONNECTION_POLICY["reconnect_max_seconds"]),
        )
        self.reconnect_stable_seconds = _positive_number(
            values, "reconnect_stable_seconds", DEFAULT_CONNECTION_POLICY["reconnect_stable_seconds"]
        )
        self.webcam_retry_seconds = _positive_number(
            values, "webcam_retry_seconds", DEFAULT_CONNECTION_POLICY["webcam_retry_seconds"]
        )
        if self.reconnect_attempt == 0:
            self._retry_delay = self.reconnect_initial_seconds
        else:
            self._retry_delay = min(max(self._retry_delay, self.reconnect_initial_seconds), self.reconnect_max_seconds)

    def _release_capture(self):
        safe_release(self.cap, self.source, self.backend or "captura")
        self.cap = None

    def _mark_connected(self, first_frame):
        now = time.monotonic()
        with self.lock:
            self.frame = first_frame
            self.frame_id += 1
            self.connection_state = "connected"
            self.connected_at = now
            self.last_frame_at = now
            self.next_retry_at = None
            self.last_error = None

    def _reset_backoff_if_stable(self, now):
        if self.connected_at is not None and now - self.connected_at >= self.reconnect_stable_seconds:
            self.reconnect_attempt = 0
            self._retry_delay = self.reconnect_initial_seconds

    def _record_frame(self, frame):
        now = time.monotonic()
        with self.lock:
            self.frame = frame
            self.frame_id += 1
            self.last_frame_at = now
            self.connection_state = "connected"
        self._reset_backoff_if_stable(now)

    def _schedule_retry(self, error):
        now = time.monotonic()
        stable = self.connected_at is not None and now - self.connected_at >= self.reconnect_stable_seconds
        if stable:
            self.reconnect_attempt = 0
            self._retry_delay = self.reconnect_initial_seconds

        if self._is_webcam:
            delay = self.webcam_retry_seconds
        else:
            delay = self._retry_delay
            self._retry_delay = min(self.reconnect_max_seconds, self._retry_delay * 2)

        self.reconnect_attempt += 1
        with self.lock:
            self.last_error = error
            self.connection_state = "reconnecting"
            self.connected_at = None
            self.next_retry_at = now + delay
        LOGGER.warning(
            "Fonte %r indisponível; nova tentativa em %.1f s (tentativa %d): %s",
            self.source,
            delay,
            self.reconnect_attempt,
            getattr(error, "public_message", lambda: str(error))(),
        )
        return not self._stop_event.wait(delay)

    def _reader(self):
        while self.running and not self._stop_event.is_set():
            if self.cap is None or not self.cap.isOpened():
                try:
                    self.cap, first_frame, self.backend = open_source(
                        self.source,
                        network_open_timeout_seconds=self.network_open_timeout_seconds,
                        network_read_timeout_seconds=self.network_read_timeout_seconds,
                    )
                    self._mark_connected(first_frame)
                except SourceFailure as error:
                    self._release_capture()
                    if not self._schedule_retry(error):
                        break
                    continue
                except Exception as error:
                    LOGGER.exception("Erro inesperado ao abrir a fonte %r", self.source)
                    self._release_capture()
                    if not self._schedule_retry(error):
                        break
                    continue

                # Arquivos devem ser lidos no ritmo original; câmeras ao vivo
                # já bloqueiam em read() até o próximo quadro.
                source_text = str(self.source).lower()
                if isinstance(self.source, str) and not source_text.startswith(
                    ("rtsp://", "rtsps://", "http://", "https://")
                ):
                    try:
                        fps = self.cap.get(cv2.CAP_PROP_FPS)
                        self.read_interval = 1.0 / fps if fps and fps > 1 else 0.0
                    except cv2.error:
                        self.read_interval = 0.0

            try:
                ok, frame = self.cap.read()
            except cv2.error as error:
                LOGGER.exception("OpenCV falhou ao ler a fonte %r", self.source)
                ok, frame = False, None
            except Exception as error:
                LOGGER.exception("Erro inesperado ao ler a fonte %r", self.source)
                ok, frame = False, None

            if not ok or frame is None:
                error = SourceFailure(
                    "WEBCAM_READ_FAILED" if self._is_webcam else "SOURCE_READ_FAILED",
                    "A webcam parou de entregar quadros." if self._is_webcam else "A fonte parou de entregar quadros.",
                )
                self._release_capture()
                if not self._schedule_retry(error):
                    break
                continue

            self._record_frame(frame)
            if self.read_interval:
                self._stop_event.wait(self.read_interval)

    def status(self):
        """Return a serializable health snapshot for the panel and logs."""
        now = time.monotonic()
        with self.lock:
            state = self.connection_state
            if state == "connected" and self.last_frame_at is not None:
                if now - self.last_frame_at > self.frame_stall_timeout_seconds:
                    state = "stalled"
            retry_in = max(0.0, self.next_retry_at - now) if self.next_retry_at else None
            error = self.last_error
            return {
                "state": state,
                "reconnect_attempt": self.reconnect_attempt,
                "retry_in_seconds": round(retry_in, 1) if retry_in is not None else None,
                "last_frame_age_seconds": round(now - self.last_frame_at, 1) if self.last_frame_at else None,
                "error_code": getattr(error, "code", type(error).__name__) if error else None,
                "error_message": str(error) if error else None,
            }

    def read(self):
        """Retorna (frame_id, frame) mais recente, ou (0, None)."""
        with self.lock:
            if self.frame is None:
                return 0, None
            return self.frame_id, self.frame.copy()

    def __iter__(self):
        return self

    def __next__(self):
        while self.running:
            frame_id, frame = self.read()
            if frame is not None and frame_id != self._last_id:
                self._last_id = frame_id
                return frame
            self._stop_event.wait(0.01)
        raise StopIteration

    def release(self):
        self.running = False
        self._stop_event.set()
        self._release_capture()

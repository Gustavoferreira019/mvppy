import os
import threading
import time
import logging

import cv2

from .source import SourceFailure, open_source, safe_release


os.environ.setdefault("OPENCV_FFMPEG_CAPTURE_OPTIONS", "rtsp_transport;tcp")
LOGGER = logging.getLogger("vigilai.capture")


class Capture:
    """Leitura contínua de uma fonte sem deixar exceções derrubarem o app."""

    def __init__(self, source, reconnect_delay: float = 3.0):
        self.source = source
        self.reconnect_delay = reconnect_delay
        self.cap = None
        self.frame = None
        self.frame_id = 0
        self._last_id = 0
        self.running = True
        self.lock = threading.Lock()
        self.read_interval = 0.0
        self.last_error = None
        self.backend = None
        self._thread = threading.Thread(target=self._reader, daemon=True, name=f"capture-{source}")
        self._thread.start()

    def _release_capture(self):
        safe_release(self.cap, self.source, self.backend or "captura")
        self.cap = None

    def _reader(self):
        while self.running:
            if self.cap is None or not self.cap.isOpened():
                try:
                    self.cap, first_frame, self.backend = open_source(self.source)
                    self.last_error = None
                    with self.lock:
                        self.frame = first_frame
                        self.frame_id += 1
                except SourceFailure as error:
                    self.last_error = error
                    LOGGER.warning(
                        "Fonte %r indisponível: %s (%s)",
                        self.source,
                        error.public_message(),
                        error.detail,
                    )
                    self._release_capture()
                    time.sleep(self.reconnect_delay)
                    continue
                except Exception as error:
                    self.last_error = error
                    LOGGER.exception("Erro inesperado ao abrir a fonte %r", self.source)
                    self._release_capture()
                    time.sleep(self.reconnect_delay)
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
                    except Exception:
                        self.read_interval = 0.0

            try:
                ok, frame = self.cap.read()
            except cv2.error as error:
                self.last_error = error
                LOGGER.exception("OpenCV falhou ao ler a fonte %r", self.source)
                ok, frame = False, None
            except Exception as error:
                self.last_error = error
                LOGGER.exception("Erro inesperado ao ler a fonte %r", self.source)
                ok, frame = False, None

            if not ok or frame is None:
                self._release_capture()
                time.sleep(self.reconnect_delay)
                continue

            with self.lock:
                self.frame = frame
                self.frame_id += 1
            if self.read_interval:
                time.sleep(self.read_interval)

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
            time.sleep(0.01)
        raise StopIteration

    def release(self):
        self.running = False
        self._release_capture()

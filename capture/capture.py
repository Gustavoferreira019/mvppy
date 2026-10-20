import os
import threading
import time
import cv2

os.environ.setdefault("OPENCV_FFMPEG_CAPTURE_OPTIONS", "rtsp_transport;tcp")


class Capture:
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
        threading.Thread(target=self._reader, daemon=True).start()

    def _reader(self):
        while self.running:
            if self.cap is None or not self.cap.isOpened():
                # Dispositivos locais (ex.: webcam 0) usam o backend padrão.
                # URLs RTSP usam FFmpeg para permitir transporte TCP.
                if isinstance(self.source, int):
                    # DirectShow evita as falhas assÃ­ncronas do MSMF em webcams
                    # do Windows durante reconexÃµes.
                    self.cap = cv2.VideoCapture(self.source, cv2.CAP_DSHOW)
                else:
                    self.cap = cv2.VideoCapture(self.source, cv2.CAP_FFMPEG)
                if not self.cap.isOpened():
                    time.sleep(self.reconnect_delay)
                    continue
                if isinstance(self.source, int):
                    for _ in range(5):
                        if not self.cap.grab():
                            break
                # Arquivos devem ser lidos no ritmo original; câmeras ao vivo
                # já bloqueiam em read() até o próximo quadro.
                source_text = str(self.source).lower()
                if isinstance(self.source, str) and not source_text.startswith(("rtsp://", "rtsps://", "http://", "https://")):
                    fps = self.cap.get(cv2.CAP_PROP_FPS)
                    self.read_interval = 1.0 / fps if fps and fps > 1 else 0.0

            ok, frame = self.cap.read()
            if not ok:
                self.cap.release()
                self.cap = None
                time.sleep(self.reconnect_delay)
                continue

            with self.lock:
                self.frame = frame
                self.frame_id += 1
            if self.read_interval:
                time.sleep(self.read_interval)

    def read(self):
        """Retorna (frame_id, frame) mais recente, ou (0, None) se ainda não chegou."""
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
        if self.cap is not None:
            self.cap.release()

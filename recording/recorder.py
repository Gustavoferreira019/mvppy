from collections import deque
from datetime import datetime
import json
from pathlib import Path

import cv2


class EventRecorder:
    """Mantém um buffer e salva clipes com alguns segundos antes/depois do evento."""

    def __init__(self, output_dir="events", fps=20.0, before_seconds=10.0, after_seconds=5.0):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.fps = max(float(fps), 1.0)
        self.buffer = deque(maxlen=max(1, int(self.fps * before_seconds)))
        self.after_seconds = max(float(after_seconds), 0.0)
        self.writer = None
        self.active_event = None
        self.finish_at = None

    def process(self, frame, events):
        self.buffer.append(frame.copy())
        if self.writer is None and events:
            self._start(frame, events[0])
            return
        if self.writer is not None:
            self.writer.write(frame)
            if datetime.now().timestamp() >= self.finish_at:
                self._finish()

    def close(self):
        if self.writer is not None:
            self._finish()

    def _start(self, frame, event):
        height, width = frame.shape[:2]
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        video_path = self.output_dir / f"event_{stamp}.mp4"
        metadata_path = self.output_dir / f"event_{stamp}.json"
        writer = cv2.VideoWriter(
            str(video_path), cv2.VideoWriter_fourcc(*"mp4v"), self.fps, (width, height)
        )
        if not writer.isOpened():
            raise RuntimeError(f"Não foi possível criar o vídeo do evento: {video_path}")
        for buffered_frame in self.buffer:
            writer.write(buffered_frame)
        self.writer = writer
        self.active_event = {**event, "video": str(video_path), "metadata": str(metadata_path)}
        self.metadata_path = metadata_path
        self.finish_at = datetime.now().timestamp() + self.after_seconds

    def _finish(self):
        self.writer.release()
        self.metadata_path.write_text(
            json.dumps(self.active_event, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        self.writer = None
        self.active_event = None
        self.finish_at = None

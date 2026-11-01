from collections import deque
from datetime import datetime
import json
from pathlib import Path
import re
import unicodedata

import cv2


class EventRecorder:
    """Mantém buffers e organiza incidentes e referências por área."""

    def __init__(self, output_dir="events", fps=20.0, before_seconds=10.0, after_seconds=5.0, max_event_seconds=60.0):
        self.output_dir = Path(output_dir)
        self.incidents_dir = self.output_dir / "incidents"
        self.incidents_dir.mkdir(parents=True, exist_ok=True)
        self.fps = max(float(fps), 1.0)
        self.buffer = deque(maxlen=max(1, int(self.fps * before_seconds)))
        self.annotated_buffer = deque(maxlen=self.buffer.maxlen)
        self.after_seconds = max(float(after_seconds), 0.0)
        self.max_event_seconds = max(float(max_event_seconds), self.after_seconds)
        self.writer = None
        self.annotated_writer = None
        self.active_event = None
        self.finish_at = None
        self.started_at = None
        self.incident_id = None
        self._area_directories = {}

    def process(self, frame, events, annotated_frame=None):
        self.buffer.append(frame.copy())
        analyzed = annotated_frame if annotated_frame is not None else frame
        self.annotated_buffer.append(analyzed.copy())
        if self.writer is None and events:
            self._start(frame, events[0])
            return
        if self.writer is not None:
            if events:
                self.active_event["timeline"].extend(events)
                now = datetime.now().timestamp()
                self.finish_at = min(
                    self.started_at + self.max_event_seconds,
                    max(self.finish_at, now + self.after_seconds),
                )
            self.writer.write(frame)
            if self.annotated_writer is not None:
                self.annotated_writer.write(analyzed)
            if datetime.now().timestamp() >= self.finish_at:
                self._finish()

    def close(self):
        if self.writer is not None:
            self._finish()

    def _start(self, frame, event):
        height, width = frame.shape[:2]
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        self.incident_id = f"event_{stamp}"
        incident_dir = self.incidents_dir / self.incident_id
        incident_dir.mkdir(parents=True, exist_ok=False)
        video_path = incident_dir / "original.mp4"
        annotated_video_path = incident_dir / "analise.mp4"
        metadata_path = incident_dir / "evento.json"
        writer = cv2.VideoWriter(
            str(video_path), cv2.VideoWriter_fourcc(*"mp4v"), self.fps, (width, height)
        )
        if not writer.isOpened():
            raise RuntimeError(f"Não foi possível criar o vídeo do evento: {video_path}")
        annotated_writer = cv2.VideoWriter(
            str(annotated_video_path), cv2.VideoWriter_fourcc(*"mp4v"), self.fps, (width, height)
        )
        if not annotated_writer.isOpened():
            writer.release()
            raise RuntimeError(f"Não foi possível criar o vídeo analisado do evento: {annotated_video_path}")
        for buffered_frame in self.buffer:
            writer.write(buffered_frame)
        for buffered_frame in self.annotated_buffer:
            annotated_writer.write(buffered_frame)
        self.writer = writer
        self.annotated_writer = annotated_writer
        self.active_event = {
            **event,
            "timeline": [event],
            "incident_id": self.incident_id,
            "incident_dir": str(incident_dir),
            "video": str(video_path),
            "annotated_video": str(annotated_video_path),
            "metadata": str(metadata_path),
        }
        self.metadata_path = metadata_path
        self.started_at = datetime.now().timestamp()
        self.finish_at = self.started_at + self.after_seconds

    @staticmethod
    def _safe_segment(value, fallback):
        normalized = unicodedata.normalize("NFKD", str(value or "")).encode("ascii", "ignore").decode()
        segment = re.sub(r"[^a-zA-Z0-9]+", "-", normalized).strip("-").lower()
        return (segment or fallback)[:64]

    def _area_directory(self, zone_id, zone_name):
        """Return a stable, human-readable folder for one configured area."""
        known = self._area_directories.get(str(zone_id))
        if known is not None:
            return known
        return self.output_dir / self._safe_segment(zone_name, "area")

    def register_areas(self, zones):
        """Materialize one directory per configured area for direct browsing."""
        configured = [zone for zone in (zones or []) if isinstance(zone, dict)]
        names = [self._safe_segment(zone.get("name"), "area") for zone in configured]
        duplicate_names = {name for name in names if names.count(name) > 1}
        self._area_directories = {}
        for zone, folder_name in zip(configured, names):
            zone_id = str(zone.get("id") or "main")
            zone_name = str(zone.get("name") or "Área monitorada")
            if folder_name in duplicate_names:
                folder_name = f"{folder_name}__{self._safe_segment(zone_id, 'main')}"
            area_dir = self.output_dir / folder_name
            self._area_directories[zone_id] = area_dir
            area_dir.mkdir(parents=True, exist_ok=True)
            area_metadata = {
                "id": zone_id,
                "name": zone_name,
                "type": zone.get("type", "interest"),
                "coordinates": zone.get("coordinates", [0, 0, 1, 1]),
            }
            (area_dir / "area.json").write_text(
                json.dumps(area_metadata, ensure_ascii=False, indent=2), encoding="utf-8"
            )

    def _write_area_indexes(self):
        """Write small references for every area touched by one incident.

        Videos remain stored once in ``incidents``. Area directories contain
        searchable JSON references, avoiding duplicated MP4 files when a
        tracked person moves through multiple areas.
        """
        timeline = self.active_event.get("timeline", [])
        indexed = set()
        for event in timeline:
            zone_id = str(event.get("zone_id") or "main")
            zone_name = str(event.get("zone_name") or "Área monitorada")
            key = (zone_id, zone_name)
            if key in indexed:
                continue
            indexed.add(key)
            area_dir = self._area_directory(zone_id, zone_name)
            area_dir.mkdir(parents=True, exist_ok=True)
            reference = {
                "incident_id": self.incident_id,
                "area": {
                    "id": zone_id,
                    "name": zone_name,
                    "type": event.get("zone_type", "interest"),
                },
                "video": self.active_event["video"],
                "annotated_video": self.active_event["annotated_video"],
                "metadata": self.active_event["metadata"],
                "timeline": timeline,
            }
            (area_dir / f"{self.incident_id}.json").write_text(
                json.dumps(reference, ensure_ascii=False, indent=2), encoding="utf-8"
            )

    def _finish(self):
        self.writer.release()
        if self.annotated_writer is not None:
            self.annotated_writer.release()
        self.metadata_path.write_text(
            json.dumps(self.active_event, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        self._write_area_indexes()
        self.writer = None
        self.annotated_writer = None
        self.active_event = None
        self.finish_at = None
        self.started_at = None
        self.incident_id = None

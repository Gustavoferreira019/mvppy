from datetime import datetime, timezone
import re


class EventEngine:
    """Transforma detecções configuradas em eventos explicáveis."""

    def __init__(self, zone, cooldown_seconds: float = 10.0, classes=None, zones=None):
        self.zone = tuple(float(value) for value in zone)
        self.cooldown_seconds = float(cooldown_seconds)
        self.allowed_classes = {
            str(value).strip().casefold()
            for value in (classes or [])
            if str(value).strip()
        }
        self.zones = zones or [{
            "id": "main",
            "name": "Área monitorada",
            "type": "interest",
            "coordinates": list(self.zone),
        }]
        self._inside = set()
        self._last_event_at = {}

    def process(self, detections, frame_shape):
        height, width = frame_shape[:2]
        current_inside = set()
        events = []
        now = datetime.now(timezone.utc)

        for index, detection in enumerate(detections):
            left, top, right, bottom = detection.box
            center = ((left + right) / 2, (top + bottom) / 2)
            label = detection.label.casefold()
            if self.allowed_classes and label not in self.allowed_classes:
                continue

            matching_zone = None
            for configured_zone in self.zones:
                coordinates = configured_zone.get("coordinates", self.zone)
                zx1, zy1, zx2, zy2 = [float(value) for value in coordinates]
                candidate = (zx1 * width, zy1 * height, zx2 * width, zy2 * height)
                if candidate[0] <= center[0] <= candidate[2] and candidate[1] <= center[1] <= candidate[3]:
                    matching_zone = configured_zone
                    break
            if matching_zone is None:
                continue

            detection_key = (
                f"{label}:{detection.track_id}"
                if detection.track_id is not None
                else f"{label}:anonymous-{index}"
            )
            current_inside.add(detection_key)

            previous = self._last_event_at.get(detection_key)
            elapsed = (now - previous).total_seconds() if previous else None
            if detection_key not in self._inside and (elapsed is None or elapsed >= self.cooldown_seconds):
                event_label = re.sub(r"[^a-z0-9]+", "_", label).strip("_") or "objeto"
                event = {
                    "type": f"{event_label}_in_restricted_zone",
                    "label": detection.label,
                    "class_id": detection.class_id,
                    "track_id": detection.track_id,
                    "confidence": detection.conf,
                    "zone": list(matching_zone.get("coordinates", self.zone)),
                    "zone_id": matching_zone.get("id", "main"),
                    "zone_name": matching_zone.get("name", "Área monitorada"),
                    "occurred_at": now.isoformat(),
                }
                events.append(event)
                self._last_event_at[detection_key] = now

        self._inside = current_inside
        return events

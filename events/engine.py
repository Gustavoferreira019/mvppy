from datetime import datetime, timezone
import re


class EventEngine:
    """Converte detecções dentro da zona em eventos simples e explicáveis."""

    def __init__(self, zone, cooldown_seconds: float = 10.0):
        self.zone = tuple(float(value) for value in zone)
        self.cooldown_seconds = cooldown_seconds
        self._inside = set()
        self._last_event_at = {}

    def process(self, detections, frame_shape):
        height, width = frame_shape[:2]
        x1, y1, x2, y2 = self.zone
        zone = (x1 * width, y1 * height, x2 * width, y2 * height)
        current_inside = set()
        events = []
        now = datetime.now(timezone.utc)

        for index, detection in enumerate(detections):
            left, top, right, bottom = detection.box
            center = ((left + right) / 2, (top + bottom) / 2)
            label = detection.label.casefold()
            detection_key = (
                f"{label}:{detection.track_id}"
                if detection.track_id is not None
                else f"{label}:anonymous-{index}"
            )
            is_inside = zone[0] <= center[0] <= zone[2] and zone[1] <= center[1] <= zone[3]

            if not is_inside:
                continue
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
                    "zone": list(self.zone),
                    "occurred_at": now.isoformat(),
                }
                events.append(event)
                self._last_event_at[detection_key] = now

        self._inside = current_inside
        return events

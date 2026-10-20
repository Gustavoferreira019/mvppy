from dataclasses import asdict
from datetime import datetime, timezone


class EventEngine:
    """Converte rastreamento de pessoas em eventos simples e explicáveis."""

    def __init__(self, zone, cooldown_seconds: float = 10.0):
        self.zone = tuple(float(value) for value in zone)
        self.cooldown_seconds = cooldown_seconds
        self._inside = set()
        self._last_event_at = {}

    def process(self, people, frame_shape):
        height, width = frame_shape[:2]
        x1, y1, x2, y2 = self.zone
        zone = (x1 * width, y1 * height, x2 * width, y2 * height)
        current_inside = set()
        events = []
        now = datetime.now(timezone.utc)

        for index, person in enumerate(people):
            left, top, right, bottom = person.box
            center = ((left + right) / 2, (top + bottom) / 2)
            person_key = person.track_id if person.track_id is not None else f"anonymous-{index}"
            is_inside = zone[0] <= center[0] <= zone[2] and zone[1] <= center[1] <= zone[3]

            if not is_inside:
                continue
            current_inside.add(person_key)

            previous = self._last_event_at.get(person_key)
            elapsed = (now - previous).total_seconds() if previous else None
            if person_key not in self._inside and (elapsed is None or elapsed >= self.cooldown_seconds):
                event = {
                    "type": "person_in_restricted_zone",
                    "track_id": person.track_id,
                    "confidence": person.conf,
                    "zone": list(self.zone),
                    "occurred_at": now.isoformat(),
                }
                events.append(event)
                self._last_event_at[person_key] = now

        self._inside = current_inside
        return events

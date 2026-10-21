import cv2

# Ligações entre os 17 keypoints do formato COCO (o que os modelos -pose do YOLO usam)
SKELETON = [
    (5, 7), (7, 9), (6, 8), (8, 10),         # braços
    (5, 6), (5, 11), (6, 12), (11, 12),      # tronco
    (11, 13), (13, 15), (12, 14), (14, 16),  # pernas
    (0, 1), (0, 2), (1, 3), (2, 4),          # rosto
]


class Renderer:

    COLORS = {
        "person": (255, 80, 80),
        "backpack": (255, 170, 0),
        "handbag": (0, 170, 255),
        "suitcase": (170, 80, 255),
        "bottle": (0, 200, 120),
        "cup": (80, 180, 255),
        "laptop": (255, 120, 180),
        "cell phone": (180, 120, 40),
    }

    def draw(self, frame, detections):
        frame_copy = frame.copy()

        for detection in detections:
            self._draw_box(frame_copy, detection)

        return frame_copy

    def _draw_box(self, image, detection):
        x1, y1, x2, y2 = map(int, detection.box)
        track = detection.track_id if detection.track_id is not None else "?"
        label = f"{detection.label} #{track} {detection.conf:.2f}"

        color = self.COLORS.get(detection.label.casefold(), (0, 255, 0))
        cv2.rectangle(image, (x1, y1), (x2, y2), color, 2)
        (text_width, text_height), baseline = cv2.getTextSize(
            label, cv2.FONT_HERSHEY_SIMPLEX, 0.6, 2
        )
        text_y = max(y1 - 6, text_height + baseline + 2)
        cv2.rectangle(image, (x1, text_y - text_height - baseline - 4), (x1 + text_width + 6, text_y + 2), color, -1)
        cv2.putText(image, label, (x1 + 3, text_y - 2),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 2)

    def _draw_skeleton(self, image, keypoints):
        # keypoints tem shape (17, 2); ponto não detectado vem como (0, 0)
        for a, b in SKELETON:
            xa, ya = keypoints[a]
            xb, yb = keypoints[b]
            if xa > 0 and ya > 0 and xb > 0 and yb > 0:
                cv2.line(image, (int(xa), int(ya)), (int(xb), int(yb)), (255, 0, 0), 2)

        for x, y in keypoints:
            if x > 0 and y > 0:
                cv2.circle(image, (int(x), int(y)), 3, (0, 0, 255), -1)

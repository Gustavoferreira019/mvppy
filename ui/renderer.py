import cv2

# Ligações entre os 17 keypoints do formato COCO (o que os modelos -pose do YOLO usam)
SKELETON = [
    (5, 7), (7, 9), (6, 8), (8, 10),         # braços
    (5, 6), (5, 11), (6, 12), (11, 12),      # tronco
    (11, 13), (13, 15), (12, 14), (14, 16),  # pernas
    (0, 1), (0, 2), (1, 3), (2, 4),          # rosto
]


class Renderer:

    def draw(self, frame, detections):
        frame_copy = frame.copy()

        for detection in detections:
            self._draw_box(frame_copy, detection)

        return frame_copy

    def _draw_box(self, image, detection):
        x1, y1, x2, y2 = map(int, detection.box)
        track = detection.track_id if detection.track_id is not None else "?"
        label = f"{detection.label} #{track} {detection.conf:.2f}"

        cv2.rectangle(image, (x1, y1), (x2, y2), (0, 255, 0), 2)
        cv2.putText(image, label, (x1, max(y1 - 6, 12)),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2)

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

from dataclasses import dataclass
import numpy as np
from ultralytics import YOLO


@dataclass
class Person:
    track_id: int | None
    box: tuple          # x1, y1, x2, y2
    conf: float
    keypoints: np.ndarray | None   # (17, 2) se for modelo de pose


class Detector:
    def __init__(self, model_path: str, confidence: float, imgsz: int = 640):
        self.model = YOLO(model_path)
        self.confidence = confidence
        self.imgsz = imgsz

    def detect(self, frame) -> list[Person]:
        result = self.model.track(
            frame,
            conf=self.confidence,
            imgsz=self.imgsz,
            persist=True,      # mantém os IDs entre frames
            verbose=False,
        )[0]

        if result.boxes is None or len(result.boxes) == 0:
            return []

        boxes = result.boxes.xyxy.cpu().numpy()
        confs = result.boxes.conf.cpu().numpy()
        ids = (
            result.boxes.id.int().cpu().tolist()
            if result.boxes.id is not None
            else [None] * len(boxes)
        )
        kps = (
            result.keypoints.xy.cpu().numpy()
            if result.keypoints is not None
            else None
        )

        return [
            Person(ids[i], tuple(boxes[i]), float(confs[i]),
                   kps[i] if kps is not None else None)
            for i in range(len(boxes))
        ]
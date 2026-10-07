from ultralytics import YOLO

class Detector:
    def __init__(self, model_path: str, confidence: float):
        self.model_path = model_path
        self.confidence = confidence

        self.model = YOLO(self.model_path)

    def detect(self, frame):
        result = self.model(frame, conf=self.confidence, verbose=False)

        info = result[0]

        if len(info.keypoints) > 0:
            return info.keypoints.xy.cpu().numpy()

        return None
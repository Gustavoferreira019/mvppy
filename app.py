import cv2
 
from capture.capture import Capture
from config import load_config
from detector.detector import Detector
from ui.renderer import Renderer
 
config = load_config("./config/config.yaml")
 
video_source = config["capture"]["source"]
model_path = config["detector"]["model_path"]
confidence = config["detector"]["confidence"]
 
capture = Capture(video_source)
detector = Detector(model_path, confidence)
renderer = Renderer()
 
for frame in capture:
    keypoints = detector.detect(frame)
    annotated = renderer.draw(frame, keypoints)
 
    cv2.imshow("Video", annotated)
 
    if cv2.waitKey(25) & 0xFF == ord("q"):
        break
 
capture.release()
cv2.destroyAllWindows()
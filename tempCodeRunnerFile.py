import cv2

from capture.capture import Capture
from config import load_config

config = load_config("./config/config.yaml")

video_source = config["capture"]["source"]

capture = Capture(video_source)

for frame in capture:
    cv2.imshow("Video", frame)
    if cv2.waitKey(25) & 0xFF == ord("q"):
        break

capture.release()
cv2.destroyAllWindows()
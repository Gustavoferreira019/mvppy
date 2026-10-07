import numpy as np

class Renderer:

    def draw(self,frame,keypoints):
        frame_copy = np.copy(frame)

        if keypoints is not None:

            for point in keypoints[0]:
            
                x,y = point

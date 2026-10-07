import cv2

class Capture():

    def __init__(self, datasource):
        self.datasource = datasource
        self.cap = cv2.VideoCapture(self.datasource)

    def __iter__(self):
        return self

    def __next__(self):
        ret, frame = self.cap.read()

        if not (ret) :
            raise StopIteration

        return frame

    def release(self):
        self.cap.release()
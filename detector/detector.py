from dataclasses import dataclass
from ultralytics import YOLO


@dataclass
class Detection:
    track_id: int | None
    box: tuple          # x1, y1, x2, y2
    conf: float
    label: str
    class_id: int


# Compatibilidade com integrações antigas que importavam Person.
Person = Detection


class Detector:
    def __init__(self, model_path: str, confidence: float, imgsz: int = 640, classes=None):
        self.model = YOLO(model_path)
        self.confidence = confidence
        self.imgsz = imgsz
        self.class_names = {
            int(class_id): str(name)
            for class_id, name in self.model.names.items()
        } if isinstance(self.model.names, dict) else {
            class_id: str(name) for class_id, name in enumerate(self.model.names)
        }
        self.configure_classes(classes)

    def configure_classes(self, classes=None):
        """Configura as classes que entram na inferência.

        Sem uma lista, o comportamento permanece compatível com a primeira
        versão e considera apenas pessoas. Uma lista vazia libera todas as
        classes disponíveis no modelo.
        """
        if classes is None:
            classes = ["person"]
        elif isinstance(classes, str):
            classes = [classes]
        if not classes:
            self.class_ids = None
            return

        aliases = {
            "human": "person",
            "people": "person",
            "pessoa": "person",
            "pessoas": "person",
        }
        available = {
            label.casefold(): class_id
            for class_id, label in self.class_names.items()
        }
        selected = []
        for value in classes:
            name = aliases.get(str(value).strip().casefold(), str(value).strip().casefold())
            if name in available:
                selected.append(available[name])
        if not selected:
            raise ValueError("Nenhuma classe configurada existe no modelo de detecção.")
        self.class_ids = sorted(set(selected))

    def detect(self, frame) -> list[Detection]:
        result = self.model.track(
            frame,
            conf=self.confidence,
            imgsz=self.imgsz,
            classes=self.class_ids,
            persist=True,      # mantém os IDs entre frames
            verbose=False,
        )[0]

        if result.boxes is None or len(result.boxes) == 0:
            return []

        boxes = result.boxes.xyxy.cpu().numpy()
        confs = result.boxes.conf.cpu().numpy()
        class_ids = result.boxes.cls.int().cpu().tolist()
        ids = (
            result.boxes.id.int().cpu().tolist()
            if result.boxes.id is not None
            else [None] * len(boxes)
        )

        return [
            Detection(
                track_id=ids[i],
                box=tuple(boxes[i]),
                conf=float(confs[i]),
                label=self.class_names.get(class_ids[i], str(class_ids[i])),
                class_id=class_ids[i],
            )
            for i in range(len(boxes))
        ]

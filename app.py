import time
import json
import hashlib
import sys
from pathlib import Path

import cv2
import numpy as np

from capture.capture import Capture
from config import load_config
from detector.detector import Detector
from events import EventEngine
from recording import EventRecorder
from ui.renderer import Renderer


BASE_DIR = Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parent
CONFIG_FILE = BASE_DIR / "config" / "config.yaml"
RUNTIME_STATUS_FILE = BASE_DIR / "runtime_status.json"
DISPLAY_CONTROL_FILE = BASE_DIR / "runtime_display.json"
RUNTIME_PREVIEW_DIR = BASE_DIR / "runtime_previews"
config = load_config(str(CONFIG_FILE))
detector_config = config["detector"]
model_path = Path(detector_config["model_path"])
if not model_path.is_absolute():
    model_path = BASE_DIR / model_path
detector = Detector(
    str(model_path),
    detector_config["confidence"],
    detector_config.get("imgsz", 640),
    detector_config.get("classes"),
)
renderer = Renderer()
RUNTIME_PREVIEW_DIR.mkdir(parents=True, exist_ok=True)
captures = {}
engines = {}
recorders = {}
last_frame_ids = {}
last_inference = {}
last_people = {}
latest = {}
last_seen = {}
last_heartbeat = 0.0
last_preview_write = {}
# A visualização é aberta somente quando o usuário solicita pelo painel.
# O processamento das câmeras continua ativo mesmo sem janela aberta.
display_enabled = False
display_camera = None


def preview_path(camera_name):
    key = hashlib.sha1(str(camera_name).encode("utf-8")).hexdigest()
    return RUNTIME_PREVIEW_DIR / f"{key}.jpg"


def draw_zone(image, zone):
    height, width = image.shape[:2]
    x1, y1, x2, y2 = [float(value) for value in zone]
    left, right = sorted((int(x1 * width), int(x2 * width)))
    top, bottom = sorted((int(y1 * height), int(y2 * height)))
    cv2.rectangle(image, (left, top), (right, bottom), (0, 122, 255), 3)


def draw_zones(image, zones):
    """Desenha áreas nomeadas sobre o quadro de análise."""
    colors = {
        "products": (255, 170, 0),
        "checkout": (0, 200, 80),
        "entrance": (255, 190, 0),
        "exit": (0, 80, 255),
        "interest": (0, 122, 255),
    }
    height, width = image.shape[:2]
    for configured_zone in zones or []:
        coordinates = configured_zone.get("coordinates", [0, 0, 1, 1])
        x1, y1, x2, y2 = [float(value) for value in coordinates]
        left, right = sorted((int(x1 * width), int(x2 * width)))
        top, bottom = sorted((int(y1 * height), int(y2 * height)))
        color = colors.get(str(configured_zone.get("type", "interest")), (0, 122, 255))
        cv2.rectangle(image, (left, top), (right, bottom), color, 3)
        label = str(configured_zone.get("name", "Área monitorada"))
        cv2.putText(image, label, (left + 6, max(top - 8, 18)), cv2.FONT_HERSHEY_SIMPLEX, 0.55, color, 2)


def write_runtime_status(running):
    payload = {
        "running": running,
        "timestamp": time.time(),
        "cameras": list(captures),
        "display_open": display_enabled,
        "display_camera": display_camera,
    }
    try:
        RUNTIME_STATUS_FILE.write_text(json.dumps(payload), encoding="utf-8")
    except OSError:
        pass


def poll_display_control():
    global display_enabled, display_camera
    try:
        command = json.loads(DISPLAY_CONTROL_FILE.read_text(encoding="utf-8"))
        DISPLAY_CONTROL_FILE.unlink(missing_ok=True)
        if command.get("action") == "open":
            display_enabled = True
            display_camera = command.get("camera") or None
    except (OSError, ValueError, TypeError):
        pass


def is_enabled(camera):
    return camera.get("enabled", True) not in (False, 0, "false", "0")


def camera_configs_from(current_config):
    capture_config = current_config["capture"]
    configured = capture_config.get("cameras")
    if configured is None:
        return [{"name": "Câmera 1", "source": capture_config["source"]}]
    return [camera for camera in configured if is_enabled(camera)]


def camera_detection_classes(camera, fallback):
    configured = camera.get("detection", {}) or {}
    classes = configured.get("classes")
    return list(classes) if isinstance(classes, list) and classes else list(fallback or [])


def reload_runtime(new_config):
    global config, inference_interval, display_interval, display_size, camera_timeout

    new_detector_config = new_config.get("detector", {})
    detector.confidence = float(new_detector_config.get("confidence", detector.confidence))
    fallback_classes = new_detector_config.get("classes") or ["person"]
    camera_list = camera_configs_from(new_config)
    # O detector executa uma inferência única com a união das classes usadas
    # pelas câmeras; cada EventEngine filtra o próprio perfil depois.
    configured_union = []
    for camera in camera_list:
        for class_name in camera_detection_classes(camera, fallback_classes):
            if class_name not in configured_union:
                configured_union.append(class_name)
    detector.configure_classes(configured_union)

    desired = {camera["name"]: camera for camera in camera_list}
    for name in list(captures):
        source_changed = name in desired and str(captures[name].source) != str(desired[name]["source"])
        if name not in desired or source_changed:
            captures[name].release()
            captures.pop(name, None)
            engines.pop(name, None)
            recorders.pop(name, None)
            last_frame_ids.pop(name, None)
            last_inference.pop(name, None)
            last_people.pop(name, None)
            latest.pop(name, None)
            last_seen.pop(name, None)

    events_config = new_config.get("events", {})
    recording_config = new_config["recording"]
    for name, camera in desired.items():
        if name not in captures:
            captures[name] = Capture(camera["source"])
            last_frame_ids[name] = 0
            last_inference[name] = 0.0
            last_people[name] = []
            recorders[name] = EventRecorder(
                output_dir=f"{recording_config['output_dir']}/{name}",
                fps=recording_config["fps"],
                before_seconds=recording_config["before_seconds"],
                after_seconds=recording_config["after_seconds"],
            )
        zone = camera.get("zone", events_config.get("restricted_zone", [0, 0, 1, 1]))
        zones = camera.get("zones") or [{
            "id": "main",
            "name": camera.get("zone_name", "Área monitorada"),
            "type": camera.get("zone_type", "interest"),
            "coordinates": zone,
        }]
        engines[name] = EventEngine(
            zone,
            events_config.get("cooldown_seconds", 10),
            classes=camera_detection_classes(camera, fallback_classes),
            zones=zones,
        )

    performance = new_config.get("performance", {})
    inference_interval = 1.0 / max(float(performance.get("inference_fps", 5)), 1.0)
    display_interval = 1.0 / max(float(performance.get("display_fps", 20)), 1.0)
    display_size = tuple(performance.get("display_size", [640, 360]))
    camera_timeout = float(performance.get("camera_timeout_seconds", 5))
    config = new_config


reload_runtime(config)
config_mtime = CONFIG_FILE.stat().st_mtime
write_runtime_status(True)

try:
    while True:
        loop_started = time.monotonic()
        poll_display_control()
        if time.monotonic() - last_heartbeat >= 1.0:
            write_runtime_status(True)
            last_heartbeat = time.monotonic()
        try:
            current_mtime = CONFIG_FILE.stat().st_mtime
            if current_mtime != config_mtime:
                time.sleep(0.05)
                updated_config = load_config(str(CONFIG_FILE))
                reload_runtime(updated_config)
                config_mtime = current_mtime
        except (OSError, ValueError, TypeError, KeyError):
            pass

        now = time.monotonic()
        panels = []
        for name, capture in list(captures.items()):
            frame_id, frame = capture.read()
            if frame is not None and frame_id != last_frame_ids[name]:
                last_frame_ids[name] = frame_id
                last_seen[name] = now
                events = []
                if now - last_inference[name] >= inference_interval:
                    last_people[name] = detector.detect(frame)
                    events = engines[name].process(last_people[name], frame.shape)
                    last_inference[name] = now
                annotated = renderer.draw(frame, last_people[name])
                draw_zones(annotated, engines[name].zones)
                cv2.putText(annotated, name, (15, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (255, 255, 255), 2)
                latest[name] = annotated
                if (not display_enabled or display_camera != name) and now - last_preview_write.get(name, 0.0) >= 0.2:
                    cv2.imwrite(
                        str(preview_path(name)),
                        annotated,
                        [cv2.IMWRITE_JPEG_QUALITY, 82],
                    )
                    last_preview_write[name] = now
                recorders[name].process(frame, events, annotated)
            if display_camera and name != display_camera:
                continue
            if name in latest and now - last_seen.get(name, 0) <= camera_timeout:
                panels.append(cv2.resize(latest[name], display_size))

        if display_enabled and panels:
            columns = 1 if len(panels) == 1 else 2 if len(panels) <= 4 else 3
            rows = (len(panels) + columns - 1) // columns
            blank = np.zeros_like(panels[0])
            panels.extend([blank] * (rows * columns - len(panels)))
            grid_rows = [cv2.hconcat(panels[row * columns:(row + 1) * columns]) for row in range(rows)]
            cv2.imshow("VIGIL.AI", cv2.vconcat(grid_rows))
            try:
                key = cv2.waitKey(1) & 0xFF
            except cv2.error:
                key = -1
            if key == ord("q"):
                display_enabled = False
                try:
                    cv2.destroyWindow("VIGIL.AI")
                except cv2.error:
                    pass
            else:
                try:
                    if cv2.getWindowProperty("VIGIL.AI", cv2.WND_PROP_VISIBLE) < 1:
                        display_enabled = False
                except cv2.error:
                    display_enabled = False
        elif display_enabled:
            # Mantém a fila de eventos do HighGUI processada mesmo sem quadro.
            try:
                cv2.waitKey(1)
            except cv2.error:
                pass
        time.sleep(max(0.001, display_interval - (time.monotonic() - loop_started)))
finally:
    write_runtime_status(False)
    for capture in captures.values():
        capture.release()
    for recorder in recorders.values():
        recorder.close()
    cv2.destroyAllWindows()

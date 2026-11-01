"""Safe OpenCV source handling shared by the runtime and configurator."""

from __future__ import annotations

import logging
import time
from typing import Any

import cv2


LOGGER = logging.getLogger("vigilai.capture")


def safe_release(cap, source, backend_name="backend"):
    """Libera uma captura sem gerar uma segunda falha no log."""
    if cap is None:
        return
    try:
        cap.release()
    except cv2.error as error:
        LOGGER.warning("OpenCV não conseguiu liberar %s da fonte %r: %s", backend_name, source, error)
    except Exception as error:
        LOGGER.warning("Não foi possível liberar %s da fonte %r: %s", backend_name, source, error)


class SourceFailure(RuntimeError):
    def __init__(self, code: str, message: str, detail: str = ""):
        super().__init__(message)
        self.code = code
        self.message = message
        self.detail = detail

    def public_message(self) -> str:
        return f"[{self.code}] {self.message}"


def normalize_source(source: Any) -> Any:
    text = "" if source is None else str(source).strip()
    if text.isdigit():
        return int(text)
    return text


def _backend_candidates(value: Any):
    if isinstance(value, int):
        # DirectShow is more stable for local Windows webcams. The default
        # backend is a fallback for drivers that do not expose DirectShow.
        return [(cv2.CAP_DSHOW, "DirectShow"), (cv2.CAP_ANY, "padrão")]
    return [(cv2.CAP_FFMPEG, "FFmpeg"), (cv2.CAP_ANY, "padrão")]


def _open_capture(value: Any, backend: int, backend_name: str, open_timeout_seconds: float | None, read_timeout_seconds: float | None):
    """Open a capture and apply FFmpeg network timeouts when supported."""
    if isinstance(value, int) or backend != cv2.CAP_FFMPEG:
        return cv2.VideoCapture(value, backend)

    params = []
    open_timeout_property = getattr(cv2, "CAP_PROP_OPEN_TIMEOUT_MSEC", None)
    read_timeout_property = getattr(cv2, "CAP_PROP_READ_TIMEOUT_MSEC", None)
    if open_timeout_property is not None and open_timeout_seconds:
        params.extend((open_timeout_property, max(1, int(open_timeout_seconds * 1000))))
    if read_timeout_property is not None and read_timeout_seconds:
        params.extend((read_timeout_property, max(1, int(read_timeout_seconds * 1000))))
    if not params:
        return cv2.VideoCapture(value, backend)

    try:
        return cv2.VideoCapture(value, backend, params)
    except (TypeError, cv2.error):
        LOGGER.warning(
            "O backend %s não aceitou timeouts de rede para %r; usando a abertura padrão.",
            backend_name,
            value,
        )
        return cv2.VideoCapture(value, backend)


def open_source(
    source: Any,
    *,
    network_open_timeout_seconds: float | None = 8.0,
    network_read_timeout_seconds: float | None = 5.0,
):
    """Open a source and return ``(capture, first_frame, backend_name)``.

    The caller owns the returned capture and must release it. All OpenCV
    exceptions are converted into a SourceFailure with a stable error code.
    """
    value = normalize_source(source)
    if value == "":
        raise SourceFailure("SOURCE_EMPTY", "Informe uma fonte de vídeo.")

    failures = []
    for backend, backend_name in _backend_candidates(value):
        cap = None
        try:
            cap = _open_capture(
                value,
                backend,
                backend_name,
                network_open_timeout_seconds,
                network_read_timeout_seconds,
            )
            if cap is None or not cap.isOpened():
                failures.append(f"{backend_name}: não abriu")
                if cap is not None:
                    safe_release(cap, value, backend_name)
                continue
            if isinstance(value, int) and backend_name == "DirectShow":
                # Alguns drivers UVC entregam quadros corrompidos quando o
                # formato padrão é YUY2. MJPG e um buffer curto evitam esse
                # problema sem exigir configuração específica do fabricante.
                try:
                    cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
                    cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
                except cv2.error:
                    LOGGER.warning("Não foi possível ajustar o formato MJPG da webcam %r", value)
            ok, frame = False, None
            read_error = None
            # Alguns drivers UVC precisam de alguns ciclos para entregar o
            # primeiro quadro depois que a captura é aberta.
            for _attempt in range(5):
                try:
                    ok, frame = cap.read()
                except cv2.error as error:
                    read_error = error
                    ok, frame = False, None
                if ok and frame is not None:
                    break
                time.sleep(0.08)
            if read_error is not None and not ok:
                failures.append(f"{backend_name}: {str(read_error).replace(chr(10), ' ')}")
            if not ok or frame is None:
                failures.append(f"{backend_name}: abriu, mas não entregou quadro")
                safe_release(cap, value, backend_name)
                continue
            return cap, frame, backend_name
        except cv2.error as error:
            detail = str(error).replace("\n", " ")
            failures.append(f"{backend_name}: {detail}")
            LOGGER.exception("OpenCV falhou ao abrir a fonte %r usando %s", value, backend_name)
            safe_release(cap, value, backend_name)
        except Exception as error:
            detail = str(error).replace("\n", " ")
            failures.append(f"{backend_name}: {detail}")
            LOGGER.exception("Falha inesperada ao abrir a fonte %r usando %s", value, backend_name)
            safe_release(cap, value, backend_name)

    frame_failed = any("abriu, mas" in failure for failure in failures)
    if isinstance(value, int) and frame_failed:
        message = "A webcam abriu, mas n\u00e3o entregou nenhum quadro. Ela pode estar ocupada por outro programa, bloqueada pelo driver ou sem permiss\u00e3o no Windows."
        code = "WEBCAM_FRAME_FAILED"
    elif isinstance(value, int):
        message = "N\u00e3o foi poss\u00edvel abrir a webcam. Ela pode estar desconectada, ocupada por outro programa ou sem permiss\u00e3o no Windows."
        code = "WEBCAM_OPEN_FAILED"
    else:
        message = "A fonte abriu, mas n\u00e3o entregou nenhum quadro." if frame_failed else "N\u00e3o foi poss\u00edvel abrir a fonte. Verifique o endere\u00e7o, credenciais, protocolo e caminho do stream."
        code = "SOURCE_FRAME_FAILED" if frame_failed else "SOURCE_OPEN_FAILED"
    raise SourceFailure(code, message, "; ".join(failures))


def probe_source(source: Any):
    """Return ``(opened, width, height, failure)`` without leaking OpenCV errors."""
    cap = None
    try:
        cap, frame, _backend = open_source(source)
        height, width = frame.shape[:2]
        return True, int(width), int(height), None
    except SourceFailure as failure:
        LOGGER.warning("Teste de fonte %r falhou: %s (%s)", source, failure.public_message(), failure.detail)
        return False, 0, 0, failure
    except Exception as error:
        LOGGER.exception("Erro inesperado ao testar a fonte %r", source)
        failure = SourceFailure("SOURCE_PROBE_ERROR", "O teste da fonte terminou com um erro inesperado.", str(error))
        return False, 0, 0, failure
    finally:
        safe_release(cap, source, "teste")

"""Simulador local de câmera ONVIF para testes do painel do VIGIL.AI.

Uso:
    venv\\Scripts\\python.exe scripts\\simulate_onvif_camera.py

O processo anuncia um dispositivo via WS-Discovery e fornece um stream MJPEG
em HTTP. Ele não deve ser incluído no pacote do cliente.
"""

from __future__ import annotations

import argparse
from datetime import datetime
import html
import re
import socket
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import cv2
import numpy as np


DISCOVERY_GROUP = "239.255.255.250"
DISCOVERY_PORT = 3702
DEFAULT_HTTP_PORT = 8890
DEFAULT_NAME = "VIGIL.AI Câmera de Teste"


def soap_response(body: str) -> bytes:
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<s:Envelope xmlns:s="http://www.w3.org/2003/05/soap-envelope">
  <s:Body>{body}</s:Body>
</s:Envelope>""".encode("utf-8")


class CameraHandler(BaseHTTPRequestHandler):
    server_version = "VIGIL-AI-Simulator/1.0"

    @property
    def simulator(self):
        return self.server.simulator_state

    def do_GET(self):
        if self.path == "/video.mjpg":
            return self.stream_video()
        if self.path in ("/onvif/device_service", "/onvif/media", "/onvif/services"):
            return self.send_text("VIGIL.AI ONVIF simulator")
        self.send_error(404)

    def do_POST(self):
        if self.path not in ("/onvif/device_service", "/onvif/media", "/onvif/services"):
            self.send_error(404)
            return
        length = int(self.headers.get("Content-Length", 0))
        request = self.rfile.read(length).decode("utf-8", errors="replace")
        if "GetCapabilities" in request:
            body = f"""
<tds:GetCapabilitiesResponse xmlns:tds="http://www.onvif.org/ver10/device/wsdl">
  <tds:Capabilities><tt:Media xmlns:tt="http://www.onvif.org/ver10/schema">
    <tt:XAddr>{self.simulator.media_url}</tt:XAddr>
  </tt:Media></tds:Capabilities>
</tds:GetCapabilitiesResponse>"""
        elif "GetProfiles" in request:
            body = """
<trt:GetProfilesResponse xmlns:trt="http://www.onvif.org/ver10/media/wsdl">
  <trt:Profiles token="profile_1"><tt:Name xmlns:tt="http://www.onvif.org/ver10/schema">Principal</tt:Name></trt:Profiles>
</trt:GetProfilesResponse>"""
        elif "GetStreamUri" in request:
            body = f"""
<trt:GetStreamUriResponse xmlns:trt="http://www.onvif.org/ver10/media/wsdl">
  <trt:MediaUri><tt:Uri xmlns:tt="http://www.onvif.org/ver10/schema">{self.simulator.stream_url}</tt:Uri></trt:MediaUri>
</trt:GetStreamUriResponse>"""
        else:
            self.send_error(400, "Operação ONVIF não suportada")
            return
        data = soap_response(body)
        self.send_response(200)
        self.send_header("Content-Type", "application/soap+xml; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def stream_video(self):
        self.send_response(200)
        self.send_header("Content-Type", "multipart/x-mixed-replace; boundary=frame")
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        try:
            while True:
                frame = self.simulator.make_frame()
                ok, encoded = cv2.imencode(".jpg", frame)
                if not ok:
                    continue
                self.wfile.write(b"--frame\r\nContent-Type: image/jpeg\r\n\r\n")
                self.wfile.write(encoded.tobytes())
                self.wfile.write(b"\r\n")
                time.sleep(0.1)
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            pass

    def send_text(self, message: str):
        data = message.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *_):
        return


class SimulatorState:
    def __init__(self, host: str, port: int, name: str):
        self.host = host
        self.port = port
        self.name = name
        self.media_url = f"http://{host}:{port}/onvif/media"
        self.stream_url = f"http://{host}:{port}/video.mjpg"

    def make_frame(self):
        frame = np.zeros((360, 640, 3), dtype=np.uint8)
        frame[:] = (36, 48, 70)
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        cv2.rectangle(frame, (24, 24), (616, 336), (65, 105, 225), 3)
        cv2.putText(frame, self.name, (48, 130), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (255, 255, 255), 2, cv2.LINE_AA)
        cv2.putText(frame, "Stream ONVIF de teste", (48, 185), cv2.FONT_HERSHEY_SIMPLEX, 0.9, (120, 220, 255), 2, cv2.LINE_AA)
        cv2.putText(frame, now, (48, 250), cv2.FONT_HERSHEY_SIMPLEX, 0.85, (220, 220, 220), 2, cv2.LINE_AA)
        return frame


def discovery_loop(state: SimulatorState, stop: threading.Event):
    probe_pattern = re.compile(r"<a:MessageID>(.*?)</a:MessageID>", re.DOTALL)
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
    membership = None
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        sock.bind(("", DISCOVERY_PORT))
        membership = socket.inet_aton(DISCOVERY_GROUP) + socket.inet_aton("0.0.0.0")
        sock.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, membership)
    except OSError as error:
        print(f"Não foi possível escutar WS-Discovery na porta {DISCOVERY_PORT}: {error}")
        sock.close()
        return
    sock.settimeout(0.5)
    try:
        while not stop.is_set():
            try:
                payload, address = sock.recvfrom(65535)
            except socket.timeout:
                continue
            text = payload.decode("utf-8", errors="ignore")
            if "Probe" not in text:
                continue
            message_id = probe_pattern.search(text)
            relates_to = html.escape(message_id.group(1) if message_id else "urn:uuid:vigilai-simulator")
            response = f"""<?xml version="1.0" encoding="UTF-8"?>
<s:Envelope xmlns:s="http://www.w3.org/2003/05/soap-envelope" xmlns:a="http://schemas.xmlsoap.org/ws/2004/08/addressing" xmlns:d="http://docs.oasis-open.org/ws-dd/ns/discovery/2009/01" xmlns:dn="http://www.onvif.org/ver10/network/wsdl">
  <s:Header><a:Action>http://schemas.xmlsoap.org/ws/2005/04/discovery/ProbeMatches</a:Action><a:RelatesTo>{relates_to}</a:RelatesTo></s:Header>
  <s:Body><d:ProbeMatches><d:ProbeMatch><d:Types>dn:NetworkVideoTransmitter</d:Types><d:Scopes>onvif://www.onvif.org/name/{html.escape(self_name(state.name))}</d:Scopes><d:XAddrs>http://{state.host}:{state.port}/onvif/device_service</d:XAddrs><d:MetadataVersion>1</d:MetadataVersion></d:ProbeMatch></d:ProbeMatches></s:Body>
</s:Envelope>""".encode("utf-8")
            try:
                sock.sendto(response, address)
            except OSError:
                pass
    finally:
        try:
            if membership is not None:
                sock.setsockopt(socket.IPPROTO_IP, socket.IP_DROP_MEMBERSHIP, membership)
        except OSError:
            pass
        sock.close()


def self_name(value: str) -> str:
    return value.replace(" ", "_")


def main():
    parser = argparse.ArgumentParser(description="Simula uma câmera ONVIF local para testes do VIGIL.AI.")
    parser.add_argument("--host", default="127.0.0.1", help="endereço usado pelo stream HTTP")
    parser.add_argument("--port", type=int, default=DEFAULT_HTTP_PORT, help=f"porta HTTP (padrão: {DEFAULT_HTTP_PORT})")
    parser.add_argument("--name", default=DEFAULT_NAME, help="nome mostrado na imagem simulada")
    args = parser.parse_args()

    state = SimulatorState(args.host, args.port, args.name)
    http_server = ThreadingHTTPServer((args.host, args.port), CameraHandler)
    http_server.simulator_state = state
    stop = threading.Event()
    discovery = threading.Thread(target=discovery_loop, args=(state, stop), daemon=True)
    discovery.start()
    http_thread = threading.Thread(target=http_server.serve_forever, daemon=True)
    http_thread.start()
    print("Simulador ONVIF ativo")
    print(f"Nome: {args.name}")
    print(f"Usuário/senha de teste: qualquer valor")
    print(f"Stream: {state.stream_url}")
    print("Abra o painel, use Buscar câmeras ONVIF e selecione o dispositivo simulado.")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\nEncerrando simulador...")
    finally:
        stop.set()
        http_server.shutdown()
        http_server.server_close()
        discovery.join(timeout=2)


if __name__ == "__main__":
    main()


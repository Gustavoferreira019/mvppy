"""Painel local de configuração do MVP.

Execute com `python setup_server.py` e abra http://127.0.0.1:8765.
"""

from html import escape
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import hashlib
import json
from pathlib import Path
import sys
import time
from urllib.parse import parse_qs, urlsplit

import cv2
import numpy as np
import yaml
from onvif_discovery import discover
from onvif_client import get_streams

if getattr(sys, "frozen", False):
    EXECUTABLE_DIR = Path(sys.executable).resolve().parent
    # No pacote Alpha o configurador fica em configurator/, enquanto os
    # arquivos persistentes ficam compartilhados em core/.
    packaged_core = EXECUTABLE_DIR.parent / "core"
    ROOT = packaged_core if (packaged_core / "config").is_dir() else EXECUTABLE_DIR
else:
    ROOT = Path(__file__).resolve().parent
CONFIG_PATH = ROOT / "config" / "config.yaml"
RUNTIME_STATUS_PATH = ROOT / "runtime_status.json"
DISPLAY_CONTROL_PATH = ROOT / "runtime_display.json"
RUNTIME_PREVIEW_DIR = ROOT / "runtime_previews"


def load_config():
    with CONFIG_PATH.open("r", encoding="utf-8") as file:
        return yaml.safe_load(file) or {}


def runtime_status():
    try:
        with RUNTIME_STATUS_PATH.open("r", encoding="utf-8") as file:
            status = json.load(file)
        return status if status.get("running") and time.time() - float(status.get("timestamp", 0)) < 5 else {}
    except (OSError, ValueError, TypeError):
        return {}


def runtime_preview_path(camera_name):
    key = hashlib.sha1(str(camera_name).encode("utf-8")).hexdigest()
    return RUNTIME_PREVIEW_DIR / f"{key}.jpg"


def probe_source(source):
    value = int(source) if source.strip().isdigit() else source.strip()
    cap = cv2.VideoCapture(value, cv2.CAP_DSHOW) if isinstance(value, int) else cv2.VideoCapture(value, cv2.CAP_FFMPEG)
    opened = cap.isOpened()
    frame = None
    if opened:
        opened, frame = cap.read()
    if opened and frame is not None:
        height, width = frame.shape[:2]
        size = (int(width), int(height))
    else:
        size = (0, 0)
        opened = False
    cap.release()
    return opened, *size


def webcam_options():
    config = load_config()
    configured = config.get("capture", {}).get("cameras", []) or []
    busy = {str(camera.get("source")): str(camera.get("name", "Câmera")) for camera in configured}
    options = []
    for index in range(5):
        if str(index) in busy:
            options.append(f"<option value='{index}' disabled>Webcam {index} (Vinculada a {escape(busy[str(index)])})</option>")
            continue
        opened, width, height = probe_source(str(index))
        if not opened:
            if index == 0:
                return "<option value=''>Nenhuma webcam detectada</option>"
            break
        options.append(f"<option value='{index}'>Webcam {index} ({width}x{height})</option>")
    return "".join(options) or "<option value=''>Nenhuma webcam detectada</option>"


class SetupHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if urlsplit(self.path).path == "/onvif/streams":
            query = parse_qs(urlsplit(self.path).query)
            try:
                user = query.get("user", [""])[0]
                password = query.get("password", [""])[0]
                xaddr = query.get("xaddr", [""])[0].strip()
                host = query.get("host", [""])[0].strip()
                candidates = [xaddr] if xaddr else []
                if host:
                    base = host if host.startswith(("http://", "https://")) else f"http://{host}"
                    candidates.extend(
                        [
                            f"{base}/onvif/device_service",
                            f"{base}/onvif/services",
                        ]
                    )
                if not candidates:
                    raise ValueError("Informe o endereço do serviço ONVIF.")
                errors = []
                for candidate in dict.fromkeys(candidates):
                    try:
                        streams = get_streams(candidate, user, password)
                        if streams:
                            return self._json(streams)
                    except Exception as error:
                        errors.append(str(error))
                detail = errors[-1] if errors else "nenhum perfil de vídeo foi informado"
                raise RuntimeError(detail)
            except Exception as error:
                return self._respond(f"Falha ONVIF: {error}", 502, "text/plain; charset=utf-8")
        if urlsplit(self.path).path == "/discover":
            devices = discover()
            data = json.dumps(devices, ensure_ascii=False).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
            return
        if urlsplit(self.path).path == "/test":
            query = parse_qs(urlsplit(self.path).query)
            source = query.get("source", [""])[0]
            source_type = query.get("type", [""])[0]
            camera_name = query.get("name", [""])[0].strip()
            linked_sources = {str(camera.get("source")): str(camera.get("name", "Câmera"))
                              for camera in load_config().get("capture", {}).get("cameras", [])}
            if not camera_name:
                return self._respond("Informe o nome da câmera antes de testar.", 400, "text/plain; charset=utf-8")
            if source_type == "webcam" and not source.isdigit():
                return self._respond("Selecione uma webcam disponível antes de testar.", 400, "text/plain; charset=utf-8")
            if source_type == "ip" and not source.lower().startswith(("rtsp://", "rtsps://")):
                return self._respond("Preencha protocolo, endereço IP, porta e caminho RTSP.", 400, "text/plain; charset=utf-8")
            if source_type == "file" and not source:
                return self._respond("Informe o caminho do arquivo de vídeo antes de testar.", 400, "text/plain; charset=utf-8")
            if source in linked_sources:
                return self._respond(f"Esta fonte já está vinculada à câmera {escape(linked_sources[source])}. Edite esse cadastro para alterar a fonte.", 409, "text/plain; charset=utf-8")
            if not source:
                return self._respond("Preencha os campos obrigatórios antes de testar.", 400, "text/plain; charset=utf-8")
            opened, width, height = probe_source(source)
            is_network = source.lower().startswith(("rtsp://", "rtsps://", "http://", "https://"))
            if opened:
                message = f"Conexão funcionando: {width}x{height}."
            elif is_network:
                message = "Falha na conexão com a câmera IP/NVR. Verifique o IP, a porta, usuário, senha e o caminho RTSP."
            else:
                message = "Não foi possível abrir a fonte de vídeo."
            return self._respond(message, 200 if opened else 502, "text/plain; charset=utf-8")
        if urlsplit(self.path).path == "/stream":
            return self._stream(urlsplit(self.path).query)
        if urlsplit(self.path).path == "/snapshot":
            query = parse_qs(urlsplit(self.path).query)
            source = query.get("source", [""])[0]
            if not source:
                return self._respond("Fonte não informada.", 400, "text/plain; charset=utf-8")
            value = int(source) if source.isdigit() else source
            cap = cv2.VideoCapture(value, cv2.CAP_DSHOW) if isinstance(value, int) else cv2.VideoCapture(value, cv2.CAP_FFMPEG)
            opened, frame = cap.isOpened(), None
            if opened:
                opened, frame = cap.read()
            cap.release()
            if not opened or frame is None:
                return self._respond(
                    "Não foi possível capturar um quadro da fonte. Verifique se a câmera está conectada e se não está sendo usada por outro programa.",
                    502,
                    "text/plain; charset=utf-8",
                )
            ok, encoded = cv2.imencode(".jpg", frame)
            if not ok:
                return self._respond("Falha ao codificar o quadro.", 500, "text/plain; charset=utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "image/jpeg")
            self.send_header("Content-Length", str(len(encoded)))
            self.end_headers()
            try:
                self.wfile.write(encoded.tobytes())
            except (BrokenPipeError, ConnectionAbortedError, ConnectionResetError):
                pass
            return
        if self.path != "/":
            self.send_error(404)
            return
        config = load_config()
        zone = config.get("events", {}).get("restricted_zone", [0, 0, 1, 1])
        recording = config.get("recording", {})
        source = str(config.get("capture", {}).get("source", ""))
        cameras = config.get("capture", {}).get("cameras", [])
        runtime = runtime_status()
        def device_icon(camera):
            device_type = str(camera.get("device_type", camera.get("type", ""))).lower()
            name = str(camera.get("name", "")).lower()
            if any(value in f"{device_type} {name}" for value in ("nvr", "gravador")):
                return "▣"
            return "<span style='display:inline-block;position:relative;width:22px;height:15px;border-radius:3px;background:#667085'><span style='position:absolute;right:-5px;top:4px;width:6px;height:7px;border-radius:1px;background:#667085'></span><span style='position:absolute;left:6px;top:3px;width:9px;height:9px;border:2px solid #fff;border-radius:50%'></span></span>"

        def camera_enabled(camera):
            configured = camera.get("enabled", True) not in (False, 0, "false", "0")
            return configured and camera.get("name") in runtime.get("cameras", [])

        green_dot = "iVBORw0KGgoAAAANSUhEUgAAAAgAAAAICAIAAABLbSncAAAAEUlEQVR42mMQ2p6FFTEMLQkA53tMwTO14RIAAAAASUVORK5CYII="
        gray_dot = "iVBORw0KGgoAAAANSUhEUgAAAAgAAAAICAIAAABLbSncAAAAEUlEQVR42mOYsWgzVsQwtCQAIdh7QTlgorsAAAAASUVORK5CYII="
        camera_rows = "".join(f"<button type='button' class='camera-card' style='display:flex;flex-direction:row;align-items:center;gap:12px;background:#f8fafc;color:#172033;border:1px solid #e4e9f2' onclick='openCamera({index})'><span class='camera-icon' aria-hidden='true' style='display:inline-flex;align-items:center;flex:0 0 28px;font-size:20px'>{device_icon(camera)}</span><span class='camera-card-content' style='display:flex;flex-direction:row;align-items:center;gap:12px'><strong>{escape(str(camera.get('name', 'Câmera')))}</strong><small class='camera-status {'active' if camera_enabled(camera) else 'inactive'}' style='display:inline-flex;align-items:center;gap:5px'><span aria-hidden='true' style='display:inline-block;width:8px;height:8px;flex:0 0 8px;border-radius:50%;background:{'#12b76a' if camera_enabled(camera) else '#98a2b3'}'></span>{'Ativa' if camera_enabled(camera) else 'Desativada'}</small></span></button>" for index, camera in enumerate(cameras))
        camera_data = json.dumps(cameras, ensure_ascii=False).replace("</", "<\\/")
        overview_cards = "".join(f"<div style='padding:14px;border:1px solid #e4e9f2;border-radius:10px;background:#f8fafc'><strong>{escape(str(camera.get('name', 'Câmera')))}</strong><br><span class='hint'>Fonte cadastrada · aguardando runtime</span></div>" for camera in cameras)
        page = f"""<!doctype html><html lang='pt-BR'><meta charset='utf-8'><title>VIGIL.AI</title>
<style>*{{box-sizing:border-box}}body{{margin:0;min-height:100vh;font:15px/1.5 -apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;color:#172033;background:linear-gradient(135deg,#eef4ff,#f8fafc)}}main{{max-width:860px;margin:38px auto;padding:34px;background:#fff;border:1px solid #e4e9f2;border-radius:18px;box-shadow:0 18px 45px rgba(37,55,88,.12)}}h1{{margin:5px 0 4px;font-size:30px}}.eyebrow{{margin:0;color:#4169e1;text-transform:uppercase;letter-spacing:.12em;font-size:12px;font-weight:800}}.intro{{margin:0 0 26px;color:#667085}}form{{display:grid;gap:13px}}label{{display:block;margin-top:4px;font-weight:700;color:#344054}}input,select{{width:100%;padding:11px 12px;margin-top:5px;border:1px solid #d0d5dd;border-radius:9px;background:#fff;color:#172033;font:inherit}}input:focus,select:focus{{outline:3px solid #dbe5ff;border-color:#4169e1}}.actions{{display:flex;gap:10px;flex-wrap:wrap;margin-top:5px}}button{{padding:11px 16px;border:0;border-radius:9px;background:#4169e1;color:white;font:600 14px inherit;cursor:pointer}}button:hover{{background:#3154bd;transform:translateY(-1px)}}button.secondary{{background:#e9efff;color:#3154bd}}.status{{display:none;margin-top:8px;padding:9px 11px;border-radius:8px;font-size:13px;font-weight:600}}.status.success{{display:block;color:#16794b;background:#e8f7ef;border:1px solid #a8e0c2}}.status.error{{display:block;color:#b42318;background:#fef0ef;border:1px solid #f5b8b3}}hr{{border:0;border-top:1px solid #e7ebf2;margin:30px 0 24px}}h2{{margin:0 0 12px;font-size:20px}}.preview-shell{{position:relative;margin-top:14px;min-height:80px;border-radius:12px;overflow:hidden;background:#f1f4f8}}.preview-shell img{{display:none;max-width:100%;width:640px}}.preview-shell canvas{{display:none;position:absolute;left:0;top:0;cursor:crosshair}}.hint{{color:#667085;font-size:13px;margin:6px 0 0}}@media(max-width:650px){{main{{margin:0;border-radius:0;padding:22px}}h1{{font-size:25px}}}}</style>
<main><p class='eyebrow'>VIGIL.AI · VIGILÂNCIA INTELIGENTE</p><h1>Monitoramento</h1><p class='intro'>Acompanhe suas câmeras e gerencie as fontes do sistema.</p><label>Seção</label><select id='sectionSelect' onchange='switchSection()'><option value='overview'>Monitoramento</option><option value='register'>Cadastrar câmera</option><option value='discover'>Encontrar câmeras ONVIF</option><option value='registered'>Câmeras cadastradas</option></select><div id='overviewSection'><h2>Visão geral</h2><p class='hint'>{len(cameras)} câmera(s) cadastrada(s). O processamento é iniciado pelo programa principal.</p><div style='display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:12px'>{overview_cards or '<div class="hint">Nenhuma câmera cadastrada ainda. Use o menu acima para começar.</div>'}</div></div><form id='cameraForm' method='post' onsubmit='return validateSave()'><h2 id='formTitle'>Cadastrar câmera</h2>
<label>Tipo de fonte</label><select id='sourceType' onchange='updateSourceMode()'><option value='webcam'>Webcam do notebook/USB</option><option value='onvif'>Câmera ONVIF (Wi-Fi ou rede)</option><option value='ip'>Câmera de rede (RTSP manual)</option></select>
<div id='webcamControls'><label>Webcams encontradas *</label><select id='webcamDevices' name='webcam_source' onchange="document.getElementById('source').value=this.value"><option value=''>Selecione</option>{webcam_options()}</select></div>
<div id='ipControls' style='display:none'><div id='onvifDiscovery'><button class='secondary' type='button' onclick='discoverCameras()'>Buscar câmeras ONVIF</button><select id='onvifDevices' style='display:none;margin-top:10px' onchange='selectDiscoveredCamera()'></select></div><label>Usuário *</label><input id='rtspUser' placeholder='usuário da câmera'><label>Senha *</label><input id='rtspPassword' type='password' placeholder='senha da câmera'><label>Endereço IP ou host *</label><input id='rtspHost' placeholder='192.168.1.50'><div id='manualRtsp'><label>Fabricante</label><select id='vendor' onchange='buildPresetPath()'><option value='intelbras'>Intelbras / Dahua</option><option value='hikvision'>Hikvision</option><option value='custom'>Outro (caminho personalizado)</option></select><label>Canal</label><input id='channel' type='number' min='1' value='1' onchange='buildPresetPath()'><label>Stream</label><select id='stream' onchange='buildPresetPath()'><option value='main'>Principal</option><option value='sub'>Secundário</option></select><label>Protocolo *</label><select id='protocol'><option value='rtsp'>RTSP</option><option value='rtsps'>RTSPS</option></select><label>Porta *</label><input id='rtspPort' value='554' placeholder='554'><label>Caminho RTSP *</label><input id='rtspPath' placeholder='/caminho/da/camera' readonly></div></div>
<div id='sourceInput' style='display:none'><input id='source' name='source' value='{escape(source)}' type='hidden'></div><p id='status' class='status'></p>
<input id='cameraId' name='camera_id' type='hidden'><label>Nome da câmera *</label><input name='camera_name' placeholder='Ex.: Entrada, Caixa ou Estoque'>
<p id='nameStatus' class='status'></p><button class='secondary' type='button' onclick='testConnection()'>Testar conexão</button>
<label>Zona (coordenadas de 0 a 1)</label><input name='x1' value='{zone[0]}' placeholder='Esquerda'><input name='y1' value='{zone[1]}' placeholder='Topo'><input name='x2' value='{zone[2]}' placeholder='Direita'><input name='y2' value='{zone[3]}' placeholder='Baixo'>
<div id='recordingSettings'><label>Segundos antes</label><input name='before' type='number' step='1' min='0' value='{int(float(recording.get("before_seconds", 10)))}'>
<label>Segundos depois</label><input name='after' type='number' step='1' min='0' value='{int(float(recording.get("after_seconds", 5)))}'>
</div>
<div class='actions'><button id='openCurrent' class='secondary' type='button' style='display:none' onclick='openCurrentCamera()'>Abrir monitoramento</button><button id='saveButton' class='primary' name='action' value='save'>Salvar configuração</button><button id='deleteCurrent' class='delete-current' type='button' style='display:none' onclick='deleteCurrentCamera()'>Excluir câmera</button></div></form><div id='registeredList'><hr><h2>Câmeras cadastradas <span class='section-count'>{len(cameras)}</span></h2><div class='camera-list'>{camera_rows or '<p class="hint">Nenhuma câmera cadastrada.</p>'}</div></div></main></html>"""
        page = page.replace("Vigilai", "VIGIL.AI")
        page = page.replace("font:15px/1.5 -apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif", "font:15px/1.5 Inter,ui-sans-serif,system-ui,-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif")
        page = page.replace("<option value='registered'>", "<option value='edit' style='display:none'>Editar câmera</option><option value='registered'>")
        page = page.replace("<label>Tipo de fonte</label>", "<label id='sourceTypeLabel'>Tipo de fonte</label>")
        page = page.replace("source.value=savedSource;", "source.value=savedSource; if(document.getElementById('linkedSourceValue')) document.getElementById('linkedSourceValue').value=savedSource;")
        page = page.replace("<div id='sourceInput'", "<div id='linkedSource' style='display:none'><label>Fonte vinculada</label><input id='linkedSourceValue' readonly></div><div id='sourceInput'")
        page = page.replace("<input id='cameraId' name='camera_id' type='hidden'>", "<input id='cameraId' name='camera_id' type='hidden'><input id='cameraNameValue' name='camera_name_value' type='hidden'>")
        page = page.replace("<input name='camera_name' placeholder=", "<input id='cameraName' name='camera_name' oninput=\"document.getElementById('cameraNameValue').value=this.value\" placeholder=")
        page = page.replace("<button class='secondary' type='button' onclick='testConnection()'>", "<button id='testConnectionButton' class='secondary' type='button' onclick='testConnection()'>")
        page = page.replace("<button class='primary' name='action' value='save'>", "<button id='saveButton' class='primary' name='action' value='save' style='display:none'>")
        page = page.replace("<button id='deleteCurrent' class='delete-current' type='button' style='display:none'", "<button id='deleteCurrent' class='delete-current' type='button' style='display:none;background:#c62828!important;color:#fff!important'")
        page = page.replace(f"value='{escape(source)}' type='hidden'", "value='' type='hidden'")
        page = page.replace("<h2 id='formTitle'>", "<h2 id='formTitle' style='margin-top:28px!important'>")
        page = page.replace("<div class='preview-shell'>", "<div class='preview-shell' style='display:inline-block;width:fit-content;max-width:100%'>")
        page = page.replace("img.onerror=()=>{{ img.style.display='none'; canvas.style.display='none'; retryButton.style.display='inline-block'; }}", "img.onerror=()=>{{ img.style.display='none'; canvas.style.display='none'; retryButton.style.display='none'; const message=document.getElementById('previewMessage'); if(message){{ message.textContent='A fonte já está sendo utilizada pelo monitoramento.'; message.style.display='block'; }} }}")
        page = page.replace("<div class='preview-shell'><img id='preview' alt=''><canvas id='zone'></canvas></div>", "<div class='preview-shell'><img id='preview' alt=''><canvas id='zone'></canvas></div><p id='previewMessage' class='hint' style='display:none'>A fonte já está sendo utilizada pelo monitoramento.</p>")
        page = page.replace("source.value=savedSource;", "source.value=savedSource; if(document.getElementById('linkedSourceValue')) document.getElementById('linkedSourceValue').value=/^[0-9]+$/.test(savedSource)?'Webcam '+savedSource:savedSource;")
        page = page.replace("function syncSource(){{ if(sourceType.value==='ip'){{ const built=buildRtsp(); if(built) source.value=built; }} }}", "function syncSource(){{ if(sourceType.value==='webcam') source.value=document.getElementById('webcamDevices').value; else if(sourceType.value==='ip'){{ const built=buildRtsp(); if(built) source.value=built; }} }}")
        page = page.replace("function syncSource(){{ if(sourceType.value==='ip'){{ const built=buildRtsp(); if(built) source.value=built; }} }}", "function syncSource(){{ if(sourceType.value==='webcam') source.value=document.getElementById('webcamDevices').value; else if(sourceType.value==='ip'){{ const built=buildRtsp(); if(built) source.value=built; }} }}")
        # Posiciona o aviso de conexão imediatamente após o nome da câmera.
        page = page.replace("<p id='status' class='status'></p>\n<input id='cameraId'", "<input id='cameraId'")
        page = page.replace("<p id='nameStatus' class='status'></p>", "<p id='status' class='status'></p><p id='nameStatus' class='status'></p>")
        page = page.replace(f"<h2>Câmeras cadastradas <span class='section-count'>{len(cameras)}</span></h2>", f"<div style='display:flex;align-items:center;justify-content:space-between;gap:16px'><h2 style='margin:0'>Câmeras cadastradas</h2><span class='section-count' style='font-size:11px;color:#667085;margin-left:auto'>{len(cameras)}</span></div>")
        page = page.replace("</style>", ".camera-card-content{display:flex;align-items:center;gap:12px}.delete-current{background:#c62828!important;color:#fff!important}.delete-current:hover{background:#9f1d1d!important;color:#fff!important;transform:none}.section-count{display:inline;font-size:11px;font-weight:600;color:#667085;background:none;min-width:0;height:auto;margin-left:4px;padding:0;vertical-align:middle}#formTitle{margin-top:28px!important}</style>")
        page = page.replace("</style>", ".preview-shell{display:inline-block;width:fit-content;max-width:100%;vertical-align:top}.preview-shell img{display:block}</style>")
        page = page.replace("</style>", "#registeredList>h2{display:flex;align-items:center;justify-content:space-between}#registeredList>h2 .section-count{margin-left:auto}.section-header{display:flex;align-items:center;justify-content:space-between;gap:16px}.section-header h2{margin:0}.section-header .section-count{margin-left:auto}.camera-status:before{display:none}</style>")
        page = page.replace("</main>", """
<div id='previewSection'><hr><h2>Prévia e zona monitorada</h2><button id='retryButton' class='secondary' style='display:none' type='button' onclick='loadPreview()'>Tentar novamente</button>
<div class='preview-shell'><img id='preview' alt=''><canvas id='zone'></canvas><div id='previewOverlay' style='display:none;position:absolute;inset:0;align-items:center;justify-content:center;color:#f2f4f7;font-size:24px;font-weight:700;background:#000'>OFFLINE</div></div>
<script>
const source=document.getElementById('source'), sourceType=document.getElementById('sourceType'), webcamControls=document.getElementById('webcamControls'), ipControls=document.getElementById('ipControls'), onvifDiscovery=document.getElementById('onvifDiscovery'), manualRtsp=document.getElementById('manualRtsp'), sourceInput=document.getElementById('sourceInput'), sourceLabel=document.getElementById('sourceLabel'), img=document.getElementById('preview'), canvas=document.getElementById('zone'), retryButton=document.getElementById('retryButton'), ctx=canvas.getContext('2d'), status=document.getElementById('status'), nameStatus=document.getElementById('nameStatus');
const registeredCameras={camera_data};
function setEditMode(editing){{ document.getElementById('formTitle').textContent=editing?'Editar câmera':'Cadastrar câmera'; document.getElementById('deleteCurrent').style.display=editing?'inline-block':'none'; document.getElementById('recordingSettings').style.display=editing?'none':'block'; }}
function openCamera(index){{ const camera=registeredCameras[index]; if(!camera)return; document.getElementById('sectionSelect').value='register'; switchSection(); document.getElementById('cameraId').value=camera.id||''; document.getElementById('deleteCurrent').style.display='inline-block'; document.querySelector('[name=camera_name]').value=camera.name||''; const savedSource=String(camera.source??''); sourceType.value=/^[0-9]+$/.test(savedSource)?'webcam':'ip'; updateSourceMode(); source.value=savedSource; if(sourceType.value==='webcam') document.getElementById('webcamDevices').value=savedSource; else {{ try {{ const url=new URL(savedSource); document.getElementById('protocol').value=url.protocol.replace(':',''); document.getElementById('rtspUser').value=decodeURIComponent(url.username||''); document.getElementById('rtspPassword').value=decodeURIComponent(url.password||''); document.getElementById('rtspHost').value=url.hostname||''; document.getElementById('rtspPort').value=url.port||'554'; document.getElementById('rtspPath').value=(url.pathname||'')+(url.search||''); }} catch(error) {{ }} }} ['x1','y1','x2','y2'].forEach((key,i)=>document.querySelector('[name='+key+']').value=(camera.zone||[0,0,1,1])[i]); status.className='status success'; status.style.display='block'; status.textContent='Câmera carregada para edição.'; setTimeout(loadPreview,0); }}
function openCurrentCamera(){{ const name=document.querySelector('[name=camera_name]').value.trim(); if(!name)return; const data=new URLSearchParams({{camera:name}}); fetch('/monitor/open',{{method:'POST',headers:{{'Content-Type':'application/x-www-form-urlencoded'}},body:data.toString()}}); }}
function deleteCurrentCamera(){{ const cameraId=document.getElementById('cameraId').value, name=document.querySelector('[name=camera_name]').value; if(!cameraId||!confirm('Excluir a câmera '+name+'?')) return; const data=new URLSearchParams({action:'delete',camera_id:cameraId}); fetch('/',{{method:'POST',headers:{{'Content-Type':'application/x-www-form-urlencoded'}},body:data}}).then(response=>{{ if(response.ok) location.reload(); else alert('Não foi possível excluir a câmera.'); }}).catch(()=>alert('Não foi possível excluir a câmera.')); }}
 function simplifyMenu(){{ const menu=document.getElementById('sectionSelect'); const overviewOption=menu.querySelector("option[value='overview']"); if(overviewOption) overviewOption.remove(); const discover=menu.querySelector("option[value='discover']"); if(discover) discover.remove(); const overview=document.getElementById('overviewSection'); if(overview) overview.remove(); menu.querySelector("option[value='register']").textContent='Adicionar câmera'; menu.querySelector("option[value='registered']").textContent='Câmeras cadastradas'; document.querySelector('h1').textContent='Configuração do VIGIL.AI'; document.querySelector('.intro').textContent='Cadastre câmeras, defina zonas e ajuste as fontes do sistema.'; }}
function switchSection(){{ const section=document.getElementById('sectionSelect').value, form=document.getElementById('cameraForm'), list=document.getElementById('registeredList'), preview=document.getElementById('previewSection'); form.style.display=section==='register'?'grid':'none'; list.style.display=section==='registered'?'block':'none'; preview.style.display=section==='register'?'block':'none'; if(section==='register' && !document.getElementById('cameraId').value) setEditMode(false); }}
let lastSourceType='webcam';
function buildRtsp(){{ const user=document.getElementById('rtspUser').value, pass=document.getElementById('rtspPassword').value, host=document.getElementById('rtspHost').value.trim(), port=document.getElementById('rtspPort').value.trim()||'554', path=document.getElementById('rtspPath').value.trim(); if(!host) return ''; const auth=user ? encodeURIComponent(user)+(pass?':'+encodeURIComponent(pass):'')+'@' : ''; return document.getElementById('protocol').value+'://'+auth+host+':'+port+(path?(path.startsWith('/')?path:'/'+path):''); }}
function buildPresetPath(){{ const vendor=document.getElementById('vendor').value, channel=document.getElementById('channel').value||'1', stream=document.getElementById('stream').value, path=document.getElementById('rtspPath'); if(vendor==='intelbras') path.value='/cam/realmonitor?channel='+channel+'&subtype='+(stream==='main'?'0':'1'); else if(vendor==='hikvision') path.value='/Streaming/Channels/'+channel+(stream==='main'?'01':'02'); else {{ path.readOnly=false; path.value=''; return; }} path.readOnly=true; }}
function discoverCameras(){{ const select=document.getElementById('onvifDevices'); select.style.display='block'; select.innerHTML='<option>Procurando câmeras...</option>'; fetch('/discover').then(response=>response.json()).then(devices=>{{ if(!devices.length){{ select.innerHTML='<option value="">Nenhuma câmera ONVIF encontrada</option>'; status.className='status error'; status.style.display='block'; status.textContent='Nenhuma câmera ONVIF encontrada. Verifique se o equipamento está na mesma rede e se o ONVIF está habilitado.'; source.value=''; return; }} status.style.display='none'; select.innerHTML='<option value="">Selecione uma câmera encontrada</option>'+devices.map((d,i)=>'<option value="'+i+'">'+d.ip+' — '+d.xaddr+'</option>').join(''); select.devices=devices; }}).catch(()=>{{ select.innerHTML='<option value="">Falha ao buscar câmeras</option>'; status.className='status error'; status.style.display='block'; status.textContent='Não foi possível procurar câmeras ONVIF nesta rede.'; }}); }}
function addRtspCredentials(uri){{ try{{ const url=new URL(uri); const user=document.getElementById('rtspUser').value.trim(), pass=document.getElementById('rtspPassword').value; if(user) url.username=user; if(pass) url.password=pass; return url.toString(); }}catch(error){{ return uri; }} }}
function selectDiscoveredCamera(){{ const select=document.getElementById('onvifDevices'), device=select.devices&&select.devices[select.value]; if(!device)return; document.getElementById('rtspHost').value=device.ip; status.className='status'; status.style.display='block'; status.textContent='Obtendo o stream da câmera ONVIF...'; const params=new URLSearchParams({{xaddr:device.xaddr,user:document.getElementById('rtspUser').value,password:document.getElementById('rtspPassword').value}}); fetch('/onvif/streams?'+params.toString()).then(async response=>{{ const streams=await response.json(); if(!response.ok||!streams.length) throw new Error('A câmera ONVIF não informou um stream de vídeo.'); source.value=addRtspCredentials(streams[0].uri); status.className='status success'; status.textContent='Câmera ONVIF encontrada. Stream pronto para teste.'; }}).catch(error=>{{ source.value=''; status.className='status error'; status.style.display='block'; status.textContent=error.message||'Não foi possível obter o stream ONVIF.'; }}); }}
function syncSource(){{ if(sourceType.value==='webcam') source.value=document.getElementById('webcamDevices').value; else if(sourceType.value==='ip'){{ const built=buildRtsp(); if(built) source.value=built; }} else if(sourceType.value==='onvif' && source.value) source.value=addRtspCredentials(source.value); }}
function validateSave(){{ syncSource(); const name=document.querySelector('[name=camera_name]').value.trim(); nameStatus.className='status'; nameStatus.style.display='none'; if(!name){{ nameStatus.className='status error'; nameStatus.style.display='block'; nameStatus.textContent='Informe um nome para a câmera antes de salvar.'; return false; }} return true; }}
function updateSourceMode(){{ const type=sourceType.value; if(type!==lastSourceType){{ source.value=''; document.getElementById('webcamDevices').value=''; ['rtspUser','rtspPassword','rtspHost','rtspPath'].forEach(id=>document.getElementById(id).value=''); img.src=''; img.style.display='none'; canvas.style.display='none'; retryButton.style.display='none'; status.className='status'; status.textContent=''; status.style.display='none'; }} lastSourceType=type; webcamControls.style.display=type==='webcam'?'block':'none'; ipControls.style.display=(type==='ip'||type==='onvif')?'block':'none'; onvifDiscovery.style.display=type==='onvif'?'block':'none'; manualRtsp.style.display=type==='ip'?'block':'none'; if(type==='ip') buildPresetPath(); }}
function testConnection(){{ syncSource(); status.className='status'; status.style.display='block'; const type=sourceType.value; if(type==='webcam' && !/^[0-9]+$/.test(source.value)){{ status.className='status error'; status.textContent='Selecione uma webcam disponível antes de testar.'; return; }} if(type==='ip' && (!document.getElementById('rtspHost').value.trim() || !document.getElementById('rtspPort').value.trim() || !document.getElementById('rtspPath').value.trim())){{ status.className='status error'; status.textContent='Preencha endereço IP, porta e caminho RTSP antes de testar.'; return; }} if(type==='onvif' && (!document.getElementById('rtspHost').value.trim() || !document.getElementById('rtspUser').value.trim() || !document.getElementById('rtspPassword').value.trim())){{ status.className='status error'; status.textContent='Preencha endereço, usuário e senha ONVIF antes de testar.'; return; }} if(type==='onvif' && !source.value){{ status.textContent='Obtendo o stream ONVIF pelo endereço informado...'; const params=new URLSearchParams({{host:document.getElementById('rtspHost').value.trim(),user:document.getElementById('rtspUser').value,password:document.getElementById('rtspPassword').value}}); fetch('/onvif/streams?'+params.toString()).then(async response=>{{ const streams=await response.json(); if(!response.ok||!streams.length) throw new Error('Não foi possível obter um stream ONVIF para esse endereço.'); source.value=addRtspCredentials(streams[0].uri); testConnection(); }}).catch(error=>{{ status.className='status error'; status.textContent=error.message||'Não foi possível obter o stream ONVIF.'; }}); return; }} status.textContent='Testando conexão...'; fetch('/test?type='+encodeURIComponent(type)+'&source='+encodeURIComponent(source.value)).then(async response=>{{ const message=await response.text(); status.className='status '+(response.ok?'success':'error'); status.textContent=message; if(response.ok) loadPreview(); }}).catch(()=>{{ status.className='status error'; status.textContent='Não foi possível testar a fonte.'; }}); }}
function loadPreview(){ if(!source.value){{ return; }} const overlay=document.getElementById('previewOverlay'); retryButton.style.display='none'; if(overlay) overlay.style.display='none'; img.style.display='none'; canvas.style.display='none'; img.onload=()=>{{ if(overlay) overlay.style.display='none'; img.style.display='block'; canvas.style.display='block'; retryButton.style.display='none'; canvas.width=img.clientWidth; canvas.height=img.clientHeight; drawZone(); }}; img.onerror=()=>{{ img.style.display='none'; canvas.style.display='none'; if(overlay){{ overlay.textContent=sourceType.value==='webcam'?'Câmera/NVR sendo utilizada':'OFFLINE'; overlay.style.display='flex'; }} retryButton.style.display='inline-block'; clearTimeout(window.previewRetryTimer); window.previewRetryTimer=setTimeout(loadPreview,5000); }}; img.src='/stream?source='+encodeURIComponent(source.value)+'&t='+Date.now(); clearInterval(window.previewPollTimer); window.previewPollTimer=setInterval(()=>{{ if(source.value && previewSection.style.display!=='none') img.src='/stream?source='+encodeURIComponent(source.value)+'&t='+Date.now(); }},1500); }
function drawZone(){ ctx.clearRect(0,0,canvas.width,canvas.height); const x1=+document.querySelector('[name=x1]').value*canvas.width,y1=+document.querySelector('[name=y1]').value*canvas.height,x2=+document.querySelector('[name=x2]').value*canvas.width,y2=+document.querySelector('[name=y2]').value*canvas.height; ctx.strokeStyle='#ff7a00';ctx.lineWidth=3;ctx.strokeRect(x1,y1,x2-x1,y2-y1); }
let start=null; canvas.addEventListener('mousedown',e=>{const r=canvas.getBoundingClientRect();start=[e.clientX-r.left,e.clientY-r.top];}); canvas.addEventListener('mouseup',e=>{if(!start)return;const r=canvas.getBoundingClientRect(),end=[e.clientX-r.left,e.clientY-r.top],x1=Math.min(start[0],end[0])/canvas.width,y1=Math.min(start[1],end[1])/canvas.height,x2=Math.max(start[0],end[0])/canvas.width,y2=Math.max(start[1],end[1])/canvas.height; [['x1',x1],['y1',y1],['x2',x2],['y2',y2]].forEach(([n,v])=>document.querySelector('[name='+n+']').value=v.toFixed(4));start=null;drawZone();});
document.querySelectorAll('.camera-card').forEach(card=>card.addEventListener('click',()=>setEditMode(true)));
updateSourceMode(); simplifyMenu(); setEditMode(false); switchSection();
</script></div></main>""")
        # O bloco acima é uma string comum (e não uma f-string), então as chaves
        # duplicadas usadas para facilitar a leitura precisam voltar ao formato JS.
        page = page.replace("{{", "{").replace("}}", "}")
        page = page.replace("{camera_data}", camera_data)
        page = page.replace("img.onerror=()=>{ img.style.display='none'; canvas.style.display='none'; retryButton.style.display='inline-block'; }", "img.onerror=()=>{ img.style.display='none'; canvas.style.display='none'; retryButton.style.display='none'; const message=document.getElementById('previewMessage'); if(message){ message.textContent='A fonte já está sendo utilizada pelo monitoramento.'; message.style.display='block'; } }")
        page = page.replace("source.value=savedSource;", "source.value=savedSource; if(document.getElementById('linkedSourceValue')) document.getElementById('linkedSourceValue').value=/^[0-9]+$/.test(savedSource)?'Webcam '+savedSource:savedSource;")
        page = page.replace("Vigilai", "VIGIL.AI")
        page = page.replace("</script></div>", """function showEditFields(editing){ const openCurrent=document.getElementById('openCurrent'); if(openCurrent) openCurrent.style.display=editing?'inline-block':'none'; const ids=['sourceTypeLabel','sourceType','webcamControls','ipControls','sourceInput','status','testConnectionButton']; ids.forEach(id=>{ const element=document.getElementById(id); if(element) element.style.display=editing?'none':''; }); const linked=document.getElementById('linkedSource'); if(linked) linked.style.display=editing?'block':'none'; document.getElementById('cameraForm').style.display=editing?'grid':''; document.getElementById('previewSection').style.display=editing?'block':''; document.getElementById('registeredList').style.display='none'; document.getElementById('formTitle').textContent=editing?'Editar câmera':'Cadastrar câmera'; document.getElementById('deleteCurrent').style.display=editing?'inline-block':'none'; document.getElementById('recordingSettings').style.display='block'; if(editing) setMonitoringView(true); else { updateSourceMode(); setMonitoringView(false); } }
function resetNewCamera(){ document.getElementById('cameraId').value=''; document.querySelector('[name=camera_name]').value=''; sourceType.value='webcam'; source.value=''; document.getElementById('webcamDevices').value=''; ['rtspUser','rtspPassword','rtspHost','rtspPath'].forEach(id=>document.getElementById(id).value=''); ['x1','y1','x2','y2'].forEach((key,i)=>document.querySelector('[name='+key+']').value=[0,0,1,1][i]); img.src=''; img.style.display='none'; canvas.style.display='none'; retryButton.style.display='none'; status.className='status'; status.textContent=''; status.style.display='none'; updateSourceMode(); }
document.querySelectorAll('.camera-card').forEach(card=>card.addEventListener('click',()=>{ document.getElementById('sectionSelect').value='edit'; showEditFields(true); }));
 document.getElementById('sectionSelect').addEventListener('change',()=>{ if(document.getElementById('sectionSelect').value==='register'){ resetNewCamera(); showEditFields(false); } });
</script></div>""")
        page = page.replace("<div class='preview-shell'>", "<div class='preview-shell' style='display:inline-block;width:fit-content;max-width:100%'>")
        page = page.replace("if(response.ok) loadPreview();", "if(response.ok){ setMonitoringView(true); loadPreview(); } else { setMonitoringView(false); retryButton.style.display='inline-block'; }")
        page = page.replace("status.className='status error'; status.style.display='block'; status.textContent='Informe o nome da câmera antes de testar.'", "nameStatus.className='status error'; nameStatus.style.display='block'; nameStatus.textContent='Informe o nome da câmera antes de testar.'")
        page = page.replace("if(type==='webcam' && !/^[0-9]+$/.test(source.value))", "if(type==='webcam' && !document.getElementById('webcamDevices').value)")
        page = page.replace("+'&source='+encodeURIComponent(source.value))", "+'&source='+encodeURIComponent(source.value)+'&name='+encodeURIComponent(document.querySelector('[name=camera_name]').value))")
        page = page.replace("function testConnection(){{ syncSource(); status.className='status';", "function testConnection(){{ syncSource(); nameStatus.className='status'; nameStatus.style.display='none'; status.className='status'; if(!document.querySelector('[name=camera_name]').value.trim()){{ nameStatus.className='status error'; nameStatus.style.display='block'; nameStatus.textContent='Informe o nome da câmera antes de testar.'; return; }}")
        page = page.replace("</script></div>", """function setMonitoringView(visible){ previewSection.style.display=visible?'block':'none'; const zoneLabel=Array.from(document.querySelectorAll('label')).find(label=>label.textContent.trim().startsWith('Zona')); if(zoneLabel){ zoneLabel.style.display=visible?'block':'none'; let field=zoneLabel.nextElementSibling; for(let i=0;i<4&&field;i++,field=field.nextElementSibling) field.style.display=visible?'block':'none'; } if(!visible){ img.style.display='none'; canvas.style.display='none'; retryButton.style.display='none'; clearInterval(window.previewPollTimer); } }
setMonitoringView(false);
</script></div>""")
        page = page.replace("resetNewCamera(); showEditFields(false);", "resetNewCamera(); showEditFields(false); setMonitoringView(false);")
        page = page.replace("setMonitoringView(false);\n</script></div>", "function setMonitoringView(visible){ previewSection.style.display=visible?'block':'none'; document.getElementById('recordingSettings').style.display=visible?'block':'none'; document.getElementById('saveButton').style.display=visible?'inline-block':'none'; const zoneLabel=Array.from(document.querySelectorAll('label')).find(label=>label.textContent.trim().startsWith('Zona')); if(zoneLabel){ zoneLabel.style.display=visible?'block':'none'; let field=zoneLabel.nextElementSibling; for(let i=0;i<4&&field;i++,field=field.nextElementSibling) field.style.display=visible?'block':'none'; } if(!visible){ img.style.display='none'; canvas.style.display='none'; retryButton.style.display='none'; clearInterval(window.previewPollTimer); } }\nsetMonitoringView(false);\n</script></div>")
        page = page.replace("<form id='cameraForm' method='post' onsubmit='return validateSave()'>", "<form id='cameraForm' method='post' onsubmit='return handleSave(event)'>")
        page = page.replace("setMonitoringView(false);\n</script></div>", """function handleSave(event){ event.preventDefault(); if(!validateSave()) return false; const button=document.getElementById('saveButton'); button.disabled=true; status.className='status'; status.style.display='block'; status.textContent='Salvando configuração...'; const form=document.getElementById('cameraForm'); const data=new URLSearchParams(new FormData(form)); data.set('action','save'); data.set('camera_name',document.querySelector('[name=camera_name]').value.trim()); data.set('source',source.value); fetch('/',{method:'POST',headers:{'Content-Type':'application/x-www-form-urlencoded;charset=UTF-8'},body:data.toString()}).then(async response=>{ const message=await response.text(); if(!response.ok) throw new Error(message.replace(/<[^>]*>/g,'').trim()||'Falha no servidor.'); status.className='status success'; status.textContent='Configuração salva com sucesso.'; document.getElementById('cameraId').value=data.get('camera_id')||''; setTimeout(()=>location.reload(),500); }).catch(error=>{ status.className='status error'; status.textContent=error.message||'Não foi possível salvar a configuração.'; }).finally(()=>{ button.disabled=false; }); return false; }
setMonitoringView(false);
</script></div>""")
        page = page.replace("</script></div>", "syncSource=function(){ if(sourceType.value==='webcam') source.value=document.getElementById('webcamDevices').value; else if(sourceType.value==='ip'){ const built=buildRtsp(); if(built) source.value=built; } else if(sourceType.value==='onvif' && source.value) source.value=addRtspCredentials(source.value); }; const _testConnection=testConnection; testConnection=function(){ syncSource(); return _testConnection(); };\n</script></div>")
        # O status de conexão deve ficar associado ao nome da câmera, logo abaixo
        # do campo, sem depender de reordenação via JavaScript no navegador.
        self._respond(page)

    def _stream(self, query_string):
        source = parse_qs(query_string).get("source", [""])[0]
        if not source:
            return self._respond("Fonte não informada.", 400, "text/plain; charset=utf-8")
        status = runtime_status()
        if status.get("running"):
            cameras = load_config().get("capture", {}).get("cameras", []) or []
            camera = next((item for item in cameras if str(item.get("source")) == source), None)
            if camera:
                display_open = bool(status.get("display_open")) and status.get("display_camera") == camera.get("name")
                if display_open:
                    # A câmera está sendo exibida pela janela principal. Não abrimos
                    # uma segunda captura: mostramos o estado de uso sobre fundo escuro.
                    frame = np.zeros((360, 640, 3), dtype=np.uint8)
                else:
                    # O núcleo publica o último quadro para a configuração. O desfoque
                    # deixa claro que é apenas uma referência, sem competir com a captura.
                    frame = cv2.imread(str(runtime_preview_path(camera.get("name"))))
                    if frame is None:
                        frame = np.zeros((360, 640, 3), dtype=np.uint8)
                    else:
                        frame = cv2.GaussianBlur(frame, (31, 31), 0)
                message = "Câmera/NVR sendo utilizada"
                text_size = cv2.getTextSize(message, cv2.FONT_HERSHEY_SIMPLEX, 1.0, 2)[0]
                text_x = max(12, (frame.shape[1] - text_size[0]) // 2)
                text_y = max(32, (frame.shape[0] + text_size[1]) // 2)
                cv2.putText(frame, message, (text_x, text_y), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (235, 235, 235), 2, cv2.LINE_AA)
                ok, encoded = cv2.imencode(".jpg", frame)
                if ok:
                    data = encoded.tobytes()
                    self.send_response(200)
                    self.send_header("Content-Type", "image/jpeg")
                    self.send_header("Cache-Control", "no-store")
                    self.send_header("Content-Length", str(len(data)))
                    self.end_headers()
                    self.wfile.write(data)
                    return
        value = int(source) if source.isdigit() else source
        cap = cv2.VideoCapture(value, cv2.CAP_DSHOW) if isinstance(value, int) else cv2.VideoCapture(value, cv2.CAP_FFMPEG)
        if not cap.isOpened():
            cap.release()
            return self._respond("Não foi possível abrir a fonte.", 502, "text/plain; charset=utf-8")
        first_ok, first_frame = cap.read()
        if not first_ok or first_frame is None:
            cap.release()
            return self._respond(
                "A fonte foi aberta, mas não entregou nenhum quadro. Verifique o caminho RTSP, as credenciais e o stream.",
                502,
                "text/plain; charset=utf-8",
            )
        self.send_response(200)
        self.send_header("Content-Type", "multipart/x-mixed-replace; boundary=frame")
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        try:
            ok, frame = first_ok, first_frame
            while True:
                if not ok:
                    break
                ok, encoded = cv2.imencode(".jpg", frame)
                if not ok:
                    continue
                self.wfile.write(b"--frame\r\nContent-Type: image/jpeg\r\n\r\n")
                self.wfile.write(encoded.tobytes())
                self.wfile.write(b"\r\n")
                time.sleep(0.1)
                ok, frame = cap.read()
        except (BrokenPipeError, ConnectionAbortedError, ConnectionResetError):
            pass
        finally:
            cap.release()

    def do_POST(self):
        if urlsplit(self.path).path == "/monitor/open":
            length = int(self.headers.get("Content-Length", 0))
            values = {key: items[0] for key, items in parse_qs(self.rfile.read(length).decode()).items()}
            try:
                DISPLAY_CONTROL_PATH.write_text(
                    json.dumps({
                        "action": "open",
                        "camera": values.get("camera", "").strip() or None,
                        "timestamp": time.time(),
                    }),
                    encoding="utf-8",
                )
            except OSError:
                return self._respond(
                    "Não foi possível solicitar a abertura do monitoramento.",
                    500,
                    "text/plain; charset=utf-8",
                )
            return self._respond("Monitoramento solicitado.", 200, "text/plain; charset=utf-8")
        length = int(self.headers.get("Content-Length", 0))
        values = {key: items[0] for key, items in parse_qs(self.rfile.read(length).decode()).items()}
        if values.get("action") == "delete":
            config = load_config()
            camera_id = values.get("camera_id", "").strip()
            cameras = config.setdefault("capture", {}).setdefault("cameras", [])
            original_count = len(cameras)
            cameras[:] = [camera for camera in cameras if camera.get("id") != camera_id]
            if len(cameras) == original_count:
                return self._respond("Câmera não encontrada.", 404, "text/plain; charset=utf-8")
            with CONFIG_PATH.open("w", encoding="utf-8") as file:
                yaml.safe_dump(config, file, allow_unicode=True, sort_keys=False)
            return self._respond("Câmera excluída.", 200, "text/plain; charset=utf-8")
        source = values.get("source", "").strip()
        if not source:
            source = values.get("webcam_source", "").strip()
        if not source:
            current_config = load_config()
            source = str(current_config.get("capture", {}).get("source", "")).strip()
        if not source:
            return self._respond("<h1>Informe uma fonte de vídeo.</h1>", 400)
        requested_id = values.get("camera_id", "").strip()
        busy_cameras = load_config().get("capture", {}).get("cameras", []) or []
        if any(
            str(camera.get("source")) == source
            and camera.get("id") != requested_id
            for camera in busy_cameras
        ):
            return self._respond("Esta fonte já está vinculada a outra câmera ou NVR.", 409, "text/plain; charset=utf-8")
        if values.get("action") == "test":
            opened, width, height = probe_source(source)
            message = f"Conexão funcionando: {width}x{height}." if opened else "Não foi possível abrir essa fonte."
            return self._respond(f"<h1>{escape(message)}</h1><p><a href='/'>Voltar</a></p>")
        config = load_config()
        normalized_source = int(source) if source.isdigit() else source
        def parse_number(value, default):
            try:
                return float(str(value).strip().replace(",", "."))
            except (TypeError, ValueError):
                return float(default)

        zone = [parse_number(values.get(k), d) for k, d in (("x1", 0), ("y1", 0), ("x2", 1), ("y2", 1))]
        capture = config.setdefault("capture", {})
        capture["source"] = normalized_source
        camera_name = values.get("camera_name", "").strip() or values.get("camera_name_value", "").strip() or values.get("name", "").strip() or "Câmera"
        cameras = capture.setdefault("cameras", [])
        camera_id = values.get("camera_id", "").strip() or camera_name.lower().replace(" ", "_")
        previous = next((camera for camera in cameras if camera.get("id") == camera_id), None)
        enabled = previous.get("enabled", True) if previous else True
        entry = {"id": camera_id, "name": camera_name, "source": normalized_source, "zone": zone, "enabled": enabled}
        cameras[:] = [camera for camera in cameras if camera.get("id") != camera_id and camera.get("name") != camera_name]
        cameras.append(entry)
        config.setdefault("events", {})["restricted_zone"] = zone
        config.setdefault("recording", {})["before_seconds"] = int(parse_number(values.get("before"), 10))
        config.setdefault("recording", {})["after_seconds"] = int(parse_number(values.get("after"), 5))
        with CONFIG_PATH.open("w", encoding="utf-8") as file:
            yaml.safe_dump(config, file, allow_unicode=True, sort_keys=False)
        self._respond("<h1>Configuração salva.</h1><p>O programa principal aplicará a alteração automaticamente.</p><p><a href='/'>Voltar</a></p>")

    def _respond(self, body, status=200, content_type="text/html; charset=utf-8"):
        data = body.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Cache-Control", "no-store, no-cache, must-revalidate, max-age=0")
        self.send_header("Pragma", "no-cache")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        try:
            self.wfile.write(data)
        except (BrokenPipeError, ConnectionAbortedError, ConnectionResetError):
            # O navegador pode cancelar uma prévia ao atualizar a imagem.
            pass

    def _json(self, value):
        data = json.dumps(value, ensure_ascii=False).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *_):
        return


if __name__ == "__main__":
    server = ThreadingHTTPServer(("127.0.0.1", 8765), SetupHandler)
    print("Painel disponível em http://127.0.0.1:8765")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        server.server_close()

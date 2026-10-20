"""Cliente ONVIF mínimo para obter perfis e URLs de stream."""

import base64
import hashlib
import os
from datetime import datetime, timezone
import xml.etree.ElementTree as ET

import requests


def _local(element):
    return element.tag.rsplit("}", 1)[-1]


def _text(element, name):
    for child in element.iter():
        if _local(child) == name and child.text:
            return child.text.strip()
    return ""


def _header(user, password):
    nonce = os.urandom(16)
    created = datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")
    digest = base64.b64encode(hashlib.sha1(nonce + created.encode() + password.encode()).digest()).decode()
    return f"""<wsse:Security s:mustUnderstand="1" xmlns:wsse="http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-wssecurity-secext-1.0.xsd" xmlns:wsu="http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-wssecurity-utility-1.0.xsd"><wsse:UsernameToken><wsse:Username>{user}</wsse:Username><wsse:Password Type="http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-username-token-profile-1.1#PasswordDigest">{digest}</wsse:Password><wsse:Nonce EncodingType="http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-soap-message-security-1.1#Base64Binary">{base64.b64encode(nonce).decode()}</wsse:Nonce><wsu:Created>{created}</wsu:Created></wsse:UsernameToken></wsse:Security>"""


def _call(url, body, user, password):
    envelope = f"""<s:Envelope xmlns:s="http://www.w3.org/2003/05/soap-envelope"><s:Header>{_header(user, password)}</s:Header><s:Body>{body}</s:Body></s:Envelope>"""
    response = requests.post(url, data=envelope.encode(), headers={"Content-Type": "application/soap+xml; charset=utf-8"}, timeout=8, verify=False)
    response.raise_for_status()
    return ET.fromstring(response.content)


def _find_url(root, name):
    for element in root.iter():
        if _local(element) == name and element.text and element.text.startswith(("http://", "https://")):
            return element.text.strip()
    return ""


def get_media_xaddr(device_xaddr, user, password):
    root = _call(device_xaddr, "<tds:GetCapabilities xmlns:tds='http://www.onvif.org/ver10/device/wsdl'><tds:Category>Media</tds:Category></tds:GetCapabilities>", user, password)
    return _find_url(root, "XAddr")


def get_profiles(media_xaddr, user, password):
    root = _call(media_xaddr, "<trt:GetProfiles xmlns:trt='http://www.onvif.org/ver10/media/wsdl'/>", user, password)
    profiles = []
    for element in root.iter():
        if _local(element) == "Profiles":
            token = element.attrib.get("token", "")
            name = _text(element, "Name")
            if token:
                profiles.append({"token": token, "name": name or token})
    return profiles


def get_stream_uri(media_xaddr, user, password, token):
    body = f"<trt:GetStreamUri xmlns:trt='http://www.onvif.org/ver10/media/wsdl'><trt:StreamSetup><tt:Stream xmlns:tt='http://www.onvif.org/ver10/schema'>RTP-Unicast</tt:Stream><tt:Transport xmlns:tt='http://www.onvif.org/ver10/schema'><tt:Protocol>RTSP</tt:Protocol></tt:Transport></trt:StreamSetup><trt:ProfileToken>{token}</trt:ProfileToken></trt:GetStreamUri>"
    root = _call(media_xaddr, body, user, password)
    return _find_url(root, "Uri")


def get_streams(device_xaddr, user, password):
    media = get_media_xaddr(device_xaddr, user, password)
    if not media:
        raise RuntimeError("A câmera não informou um serviço de mídia ONVIF.")
    streams = []
    for profile in get_profiles(media, user, password):
        uri = get_stream_uri(media, user, password, profile["token"])
        if uri:
            streams.append({**profile, "uri": uri})
    return streams

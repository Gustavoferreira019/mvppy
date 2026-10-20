"""Descoberta WS-Discovery de câmeras ONVIF na rede local."""

import socket
import uuid
import xml.etree.ElementTree as ET


PROBE = """<?xml version='1.0' encoding='utf-8'?>
<s:Envelope xmlns:s='http://www.w3.org/2003/05/soap-envelope' xmlns:a='http://schemas.xmlsoap.org/ws/2004/08/addressing' xmlns:d='http://docs.oasis-open.org/ws-dd/ns/discovery/2009/01' xmlns:dn='http://www.onvif.org/ver10/network/wsdl'>
<s:Header><a:Action>http://docs.oasis-open.org/ws-dd/ns/discovery/2009/01/Probe</a:Action><a:MessageID>urn:uuid:{message_id}</a:MessageID><a:To>urn:schemas-xmlsoap-org:ws:2005:04:discovery</a:To></s:Header>
<s:Body><d:Probe><d:Types>dn:NetworkVideoTransmitter</d:Types></d:Probe></s:Body></s:Envelope>"""


def discover(timeout=2.0):
    message = PROBE.format(message_id=uuid.uuid4())
    devices = {}
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    sock.settimeout(0.25)
    try:
        sock.sendto(message.encode(), ("239.255.255.250", 3702))
        deadline = socket.getdefaulttimeout() or timeout
        end = __import__("time").monotonic() + timeout
        while __import__("time").monotonic() < end:
            try:
                payload, address = sock.recvfrom(65535)
            except socket.timeout:
                continue
            try:
                root = ET.fromstring(payload)
            except ET.ParseError:
                continue
            xaddr = ""
            # O endereço da câmera fica em XAddrs. O envelope também contém
            # URLs da ação SOAP; escolher a primeira URL do XML causa falsos
            # dispositivos e impede a conexão posterior.
            for element in root.iter():
                if element.tag.rsplit("}", 1)[-1] not in {"XAddrs", "XAddr"}:
                    continue
                values = (element.text or "").split()
                xaddr = next((value for value in values if value.startswith(("http://", "https://"))), "")
                if xaddr:
                    break
            if not xaddr:
                # Compatibilidade com respostas simplificadas que não usam
                # a tag XAddrs, evitando URLs de namespaces SOAP.
                texts = [element.text.strip() for element in root.iter() if element.text and element.text.strip()]
                xaddr = next(
                    (text for text in texts if text.startswith(("http://", "https://")) and "ws-discovery" not in text),
                    "",
                )
            if xaddr:
                devices[xaddr] = {"xaddr": xaddr, "ip": address[0]}
    finally:
        sock.close()
    return list(devices.values())

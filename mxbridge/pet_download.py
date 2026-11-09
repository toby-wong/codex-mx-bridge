"""Bounded public HTTPS downloads for the settings app's pet importer."""
import http.client
import ipaddress
import json
import re
import socket
import ssl
import time
from urllib.parse import quote, urljoin, urlsplit

MAX_DOWNLOAD = 20 * 1024 * 1024
DOWNLOAD_SECONDS = 45
CATALOG = "https://codex-pets.net"
NAT64 = (ipaddress.ip_network("64:ff9b::/96"), ipaddress.ip_network("64:ff9b:1::/48"))


def parse_url(value):
    if (not isinstance(value, str) or not 0 < len(value) <= 4096 or
            any(c.isspace() or ord(c) < 32 or ord(c) == 127 or c == "\\" for c in value)):
        raise ValueError("Paste a public HTTPS pet URL, up to 4096 characters")
    parsed = urlsplit(value)
    if (parsed.scheme != "https" or not parsed.hostname or parsed.username is not None or
            parsed.password is not None or parsed.port == 0 or "%" in parsed.hostname):
        raise ValueError("Use a public HTTPS URL without a username or password")
    return parsed


def public_addresses(host, port):
    addresses = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM, proto=socket.IPPROTO_TCP)
    if not addresses:
        raise ValueError("The pet host has no public address")
    for family, _, _, _, address in addresses:
        ip = ipaddress.ip_address(address[0])
        if (family not in (socket.AF_INET, socket.AF_INET6) or not ip.is_global or
                ip.is_multicast or ip.is_reserved or
                isinstance(ip, ipaddress.IPv6Address) and
                (ip.sixtofour is not None or ip.teredo is not None or any(ip in net for net in NAT64))):
            raise ValueError("Pet URLs must use public hosts; local and private addresses are not supported")
    return addresses


def timeout(deadline):
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise ValueError("The pet download timed out; try again")
    return min(10, remaining)


def connect(parsed, deadline):
    host = parsed.hostname.encode("idna").decode("ascii")
    port = parsed.port or 443
    addresses = public_addresses(host, port)
    context = ssl.create_default_context()
    last_error = None
    for family, kind, protocol, _, address in addresses:
        transport = socket.socket(family, kind, protocol)
        try:
            transport.settimeout(timeout(deadline))
            # Dial the validated numeric address, keeping the original hostname for TLS.
            transport.connect(address)
            transport = context.wrap_socket(transport, server_hostname=host)
            connection = http.client.HTTPSConnection(host, port, timeout=timeout(deadline), context=context)
            connection.sock = transport
            return connection, transport
        except OSError as exc:
            last_error = exc
            transport.close()
        except BaseException:
            transport.close()
            raise
    raise last_error or OSError("Cannot connect to the pet host")


def download(url, *, limit=MAX_DOWNLOAD, deadline=None):
    deadline = deadline if deadline is not None else time.monotonic() + DOWNLOAD_SECONDS
    try:
        for hop in range(6):
            parsed = parse_url(url)
            timeout(deadline)
            connection, transport = connect(parsed, deadline)
            response = None
            try:
                path = quote(parsed.path or "/", safe="/:@!$&'()*+,;=-._~%")
                if parsed.query:
                    path += "?" + quote(parsed.query, safe="/?:@!$&'()*+,;=-._~%")
                transport.settimeout(timeout(deadline))
                connection.request("GET", path, headers={
                    "User-Agent": "Mozilla/5.0 (compatible; CodexMXBridge/0.3; pet importer)",
                    "Accept": "application/zip, image/png, image/webp, application/json",
                    "Accept-Encoding": "identity",
                    "Connection": "close",
                })
                response = connection.getresponse()
                if response.status in {301, 302, 303, 307, 308}:
                    location = response.getheader("Location")
                    if not location or hop == 5:
                        raise ValueError("The pet URL redirects too many times or has no download target")
                    url = urljoin(url, location)
                    continue
                if response.status != 200:
                    raise ValueError(f"The pet host returned HTTP {response.status}; check the link or download the file manually")
                if response.getheader("Content-Encoding", "identity").lower() != "identity":
                    raise ValueError("The pet host returned an unsupported transfer encoding")
                length = response.getheader("Content-Length")
                if length is not None and (not length.isdecimal() or int(length) > limit):
                    raise ValueError("The pet download exceeds its size limit (20 MiB for artwork)")
                raw = bytearray()
                while not response.isclosed():
                    transport.settimeout(timeout(deadline))
                    chunk = response.read1(min(65536, limit + 1 - len(raw)))
                    if not chunk:
                        break
                    raw.extend(chunk)
                    if len(raw) > limit:
                        raise ValueError("The pet download exceeds its size limit (20 MiB for artwork)")
                if length is not None and len(raw) != int(length):
                    raise ValueError("The pet download was incomplete; try again")
                return bytes(raw)
            finally:
                if response is not None:
                    response.close()
                connection.close()
                transport.close()
        raise ValueError("The pet URL redirects too many times")
    except (OSError, http.client.HTTPException) as exc:
        raise ValueError("Could not download the pet over HTTPS; check the link and connection, then try again") from exc


def fetch_pet(url):
    parsed = parse_url(url)
    deadline = time.monotonic() + DOWNLOAD_SECONDS
    if parsed.hostname in {"codex-pets.net", "www.codex-pets.net"} and (parsed.port or 443) == 443:
        route = parsed.fragment if parsed.fragment else parsed.path
        match = re.fullmatch(r"/pets/([a-zA-Z0-9_-]{1,128})/?", route)
        if match:
            metadata = download(f"{CATALOG}/api/pets/{match[1]}", limit=65536, deadline=deadline)
            try:
                pet = json.loads(metadata)["pet"]
                target = pet["downloadUrl"]
                if not isinstance(target, str) or not target:
                    raise ValueError("Missing pet download URL")
                url = urljoin(CATALOG, target)
            except (ValueError, KeyError, TypeError) as exc:
                raise ValueError("This Codex Pets page has no usable download; try its direct ZIP link") from exc
    raw = download(url, deadline=deadline)
    if raw.startswith(b"PK\x03\x04"):
        filename = "pet.codex-pet.zip"
    elif raw.startswith(b"\x89PNG\r\n\x1a\n"):
        filename = "pet.png"
    elif raw.startswith(b"RIFF") and raw[8:12] == b"WEBP":
        filename = "pet.webp"
    else:
        raise ValueError("The link did not return a pet ZIP, PNG or WebP. Paste a Codex Pets page or a direct file URL.")
    return raw, filename

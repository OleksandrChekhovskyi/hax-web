from __future__ import annotations

import ipaddress
import re
import urllib.parse

from . import WebError


def looks_like_ipv4(host: str) -> bool:
    parts = host.split(".")
    if not 1 <= len(parts) <= 4:
        return False
    number = re.compile(r"(?:0[xX][0-9a-fA-F]+|0[0-7]*|[1-9][0-9]*)")
    return all(number.fullmatch(part) is not None for part in parts)


def validate_public_url(value: str) -> str:
    try:
        url = urllib.parse.urlsplit(value)
        port = url.port
    except ValueError as error:
        raise WebError(f"invalid URL: {error}") from error
    if url.scheme.lower() not in {"http", "https"} or not url.hostname:
        raise WebError("URL must use http:// or https:// and include a host")
    if url.username is not None or url.password is not None:
        raise WebError("URL must not contain embedded credentials")
    if port is not None and not 1 <= port <= 65535:
        raise WebError("URL port is out of range")

    host = url.hostname.lower()
    if "%" in host:
        raise WebError("URL host must not contain percent-encoding")
    try:
        host = host.encode("idna").decode("ascii").rstrip(".")
    except UnicodeError as error:
        raise WebError(f"invalid URL host: {error}") from error

    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        address = None
    if address is not None:
        if not address.is_global or address.is_multicast:
            raise WebError("refusing to send a local or private URL to an external service")
    elif looks_like_ipv4(host):
        raise WebError("refusing to send an ambiguous IPv4 URL to an external service")
    elif "." not in host or host.endswith((".local", ".internal", ".localhost")):
        raise WebError("refusing to send a local or private URL to an external service")
    return value

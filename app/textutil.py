from __future__ import annotations

import hashlib
import ipaddress
import re
import socket
from urllib.parse import urlparse

_WORD = re.compile(r"[\w]{3,}", re.UNICODE)
_TAG = re.compile(r"<[^>]+>")


def normalize_fact(text: str) -> str:
    return " ".join(text.casefold().split())


def content_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def chunk_text(text: str, size: int = 900) -> list[str]:
    clean = "\n".join(line.rstrip() for line in text.splitlines()).strip()
    if not clean:
        return []
    paragraphs = [part.strip() for part in re.split(r"\n\s*\n", clean) if part.strip()]
    chunks: list[str] = []
    current = ""
    for paragraph in paragraphs:
        if len(paragraph) > size:
            if current:
                chunks.append(current.strip())
                current = ""
            for start in range(0, len(paragraph), size):
                piece = paragraph[start : start + size].strip()
                if piece:
                    chunks.append(piece)
            continue
        candidate = f"{current}\n\n{paragraph}".strip() if current else paragraph
        if len(candidate) <= size:
            current = candidate
        else:
            chunks.append(current.strip())
            current = paragraph
    if current:
        chunks.append(current.strip())
    return chunks


def fts_query(text: str, limit: int = 10) -> str:
    words: list[str] = []
    seen: set[str] = set()
    for match in _WORD.finditer(text.casefold()):
        word = match.group(0).replace('"', "")
        if word in seen or word.isdigit():
            continue
        seen.add(word)
        words.append(word)
        if len(words) >= limit:
            break
    if not words:
        return ""
    return " OR ".join(f'"{word}"' for word in words)


def html_to_text(raw: str) -> str:
    try:
        from bs4 import BeautifulSoup
    except ImportError:
        text = _TAG.sub(" ", raw)
        return " ".join(text.split())
    soup = BeautifulSoup(raw, "html.parser")
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()
    title = soup.title.get_text(" ", strip=True) if soup.title else ""
    body = soup.get_text("\n", strip=True)
    if title and title not in body[:200]:
        return f"{title}\n\n{body}".strip()
    return body.strip()


def _ip_allowed(ip: ipaddress.IPv4Address | ipaddress.IPv6Address, allow_private: bool) -> bool:
    if (
        ip.is_loopback
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_unspecified
        or ip.is_reserved
    ):
        return False
    if ip.is_private and not allow_private:
        return False
    return True


def url_is_allowed(url: str, allow_private: bool = False) -> tuple[bool, str]:
    parsed = urlparse(url.strip())
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        return False, "Provide a full http or https URL."
    host = parsed.hostname.strip().lower()
    if host == "localhost":
        return False, "Local addresses are blocked."
    literals: list[ipaddress.IPv4Address | ipaddress.IPv6Address] = []
    try:
        literals.append(ipaddress.ip_address(host))
    except ValueError:
        try:
            infos = socket.getaddrinfo(host, None)
        except socket.gaierror:
            return False, "Could not resolve the host name."
        for info in infos:
            address = info[4][0]
            try:
                literals.append(ipaddress.ip_address(address))
            except ValueError:
                continue
    if not literals:
        return False, "The host has no IP address."
    for ip in literals:
        if not _ip_allowed(ip, allow_private):
            return False, "That network address is blocked."
    return True, ""

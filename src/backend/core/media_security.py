"""
Media and Attachment Security Module.
Provides MIME type validation, file size enforcement, and Anti-SSRF protection for media URLs.
(Baseline Controls 20, 21, 23)
"""
import ipaddress
import socket
import urllib.parse
from typing import Tuple

# Allowed MIME types and their typical extensions
ALLOWED_MIME_TYPES = {
    "image/jpeg": [".jpg", ".jpeg"],
    "image/png": [".png"],
    "image/webp": [".webp"],
    "application/pdf": [".pdf"],
    "audio/ogg": [".ogg"],
    "audio/mpeg": [".mp3"],
    "audio/wav": [".wav"],
    "text/plain": [".txt"],
}

# Max media file size: 15 MB
MAX_FILE_SIZE_BYTES = 15 * 1024 * 1024

class SecurityValidationError(Exception):
    pass

class SSRFProtectionError(SecurityValidationError):
    pass

class MIMEValidationError(SecurityValidationError):
    pass

def validate_media_url(url: str) -> str:
    """
    Validates external media download URLs against Server-Side Request Forgery (SSRF).
    Blocks private, link-local, loopback, and non-HTTP(S) endpoints.
    """
    if not url:
        raise SSRFProtectionError("Empty URL provided")

    parsed = urllib.parse.urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise SSRFProtectionError(f"Prohibited URL scheme: '{parsed.scheme}'. Only http/https permitted.")

    hostname = parsed.hostname
    if not hostname:
        raise SSRFProtectionError("URL is missing a valid hostname")

    # Check for direct IP or resolve DNS
    try:
        ip = ipaddress.ip_address(hostname)
        resolved_ips = [ip]
    except ValueError:
        try:
            # Resolve hostname
            addr_info = socket.getaddrinfo(hostname, None)
            resolved_ips = [ipaddress.ip_address(item[4][0]) for item in addr_info]
        except socket.gaierror as e:
            raise SSRFProtectionError(f"DNS resolution failure for host '{hostname}': {e}")

    for resolved_ip in resolved_ips:
        if resolved_ip.is_private:
            raise SSRFProtectionError(f"SSRF violation: Host '{hostname}' resolves to private IP: {resolved_ip}")
        if resolved_ip.is_loopback:
            raise SSRFProtectionError(f"SSRF violation: Host '{hostname}' resolves to loopback IP: {resolved_ip}")
        if resolved_ip.is_link_local:
            raise SSRFProtectionError(f"SSRF violation: Host '{hostname}' resolves to link-local IP: {resolved_ip}")
        if resolved_ip.is_reserved:
            raise SSRFProtectionError(f"SSRF violation: Host '{hostname}' resolves to reserved IP: {resolved_ip}")
        if resolved_ip.is_multicast:
            raise SSRFProtectionError(f"SSRF violation: Host '{hostname}' resolves to multicast IP: {resolved_ip}")

    return url

def validate_attachment_metadata(file_name: str, content_type: str, file_size: int) -> Tuple[bool, str]:
    """
    Validates uploaded attachment metadata against allowed MIME types and size constraints.
    """
    if file_size <= 0:
        raise MIMEValidationError("Attachment file size must be greater than 0 bytes")
    if file_size > MAX_FILE_SIZE_BYTES:
        raise MIMEValidationError(f"Attachment file size {file_size} exceeds maximum {MAX_FILE_SIZE_BYTES} bytes")

    normalized_mime = content_type.split(";")[0].strip().lower()
    if normalized_mime not in ALLOWED_MIME_TYPES:
        raise MIMEValidationError(f"Prohibited or unsupported MIME type: '{normalized_mime}'")

    # Sanitize file name (prevent path traversal)
    clean_name = file_name.replace("/", "_").replace("\\", "_").strip()
    if not clean_name or clean_name in (".", ".."):
        clean_name = "attachment_media"

    return True, clean_name

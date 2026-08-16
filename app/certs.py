"""Self-signed TLS certificate for LAN use.

Browsers only hand out the camera in a "secure context": HTTPS, or localhost.
A phone opening http://192.168.x.x:8000 gets neither — `navigator.mediaDevices`
is not merely blocked, it is undefined, so the app cannot start the camera at
all. Serving the same app over HTTPS with a self-signed certificate fixes that;
the phone shows a one-time warning that you accept, and the camera works.

The certificate covers localhost and whatever LAN address the desktop has, and
is regenerated automatically if that address changes (new DHCP lease).
"""

from __future__ import annotations

import datetime
import ipaddress
from pathlib import Path
from typing import Iterable, Optional

from . import config

CERT_NAME = "lan-cert.pem"
KEY_NAME = "lan-key.pem"


def _paths(directory: Optional[Path] = None) -> tuple[Path, Path]:
    directory = directory or config.DATA_DIR
    return directory / CERT_NAME, directory / KEY_NAME


def covers(cert_path: Path, addresses: Iterable[str]) -> bool:
    """Is this certificate still valid and still covering these addresses?"""
    try:
        from cryptography import x509
    except ImportError:
        return False
    try:
        cert = x509.load_pem_x509_certificate(cert_path.read_bytes())
    except (OSError, ValueError):
        return False

    now = datetime.datetime.now(datetime.timezone.utc)
    if cert.not_valid_after_utc <= now:
        return False
    try:
        san = cert.extensions.get_extension_for_class(x509.SubjectAlternativeName).value
        present = {str(ip) for ip in san.get_values_for_type(x509.IPAddress)}
        present |= set(san.get_values_for_type(x509.DNSName))
    except x509.ExtensionNotFound:
        return False
    return set(addresses).issubset(present)


def generate(addresses: Iterable[str], directory: Optional[Path] = None) -> tuple[Path, Path]:
    """Write a self-signed certificate/key pair covering `addresses`."""
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import NameOID

    directory = directory or config.DATA_DIR
    directory.mkdir(parents=True, exist_ok=True)
    cert_path, key_path = _paths(directory)

    names: list[x509.GeneralName] = [x509.DNSName("localhost")]
    for address in addresses:
        try:
            names.append(x509.IPAddress(ipaddress.ip_address(address)))
        except ValueError:
            names.append(x509.DNSName(address))

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    subject = x509.Name([
        x509.NameAttribute(NameOID.COMMON_NAME, "AI Vision Dart Scorer"),
        x509.NameAttribute(NameOID.ORGANIZATION_NAME, "Dart Scorer (local)"),
    ])
    now = datetime.datetime.now(datetime.timezone.utc)
    certificate = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(subject)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - datetime.timedelta(days=1))
        # Browsers reject self-signed certificates valid for much longer.
        .not_valid_after(now + datetime.timedelta(days=397))
        .add_extension(x509.SubjectAlternativeName(names), critical=False)
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .sign(key, hashes.SHA256())
    )

    cert_path.write_bytes(certificate.public_bytes(serialization.Encoding.PEM))
    key_path.write_bytes(
        key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.TraditionalOpenSSL,
            encryption_algorithm=serialization.NoEncryption(),
        )
    )
    return cert_path, key_path


def ensure(addresses: Iterable[str], directory: Optional[Path] = None) -> tuple[Path, Path]:
    """Return a cert/key pair covering `addresses`, creating one if needed."""
    addresses = list(addresses)
    cert_path, key_path = _paths(directory)
    if cert_path.exists() and key_path.exists() and covers(cert_path, addresses):
        return cert_path, key_path
    return generate(addresses, directory)


if __name__ == "__main__":  # `python -m app.certs` from start.bat
    import sys

    from .main import lan_ip

    targets = sys.argv[1:] or [lan_ip(), "127.0.0.1"]
    cert, key = ensure(targets)
    print(f"{cert}\n{key}")

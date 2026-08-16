"""The certificate is what makes the phone camera work at all, so its
regeneration logic is worth pinning down."""

import datetime

import pytest

from app import certs

pytest.importorskip("cryptography")


def test_generate_covers_localhost_and_the_given_addresses(tmp_path):
    cert_path, key_path = certs.generate(["192.168.1.20", "127.0.0.1"], tmp_path)
    assert cert_path.exists() and key_path.exists()
    assert certs.covers(cert_path, ["192.168.1.20", "127.0.0.1", "localhost"])


def test_certificate_is_short_lived_enough_for_browsers(tmp_path):
    from cryptography import x509

    cert_path, _ = certs.generate(["10.0.0.4"], tmp_path)
    cert = x509.load_pem_x509_certificate(cert_path.read_bytes())
    lifetime = cert.not_valid_after_utc - cert.not_valid_before_utc
    # Browsers reject self-signed leaf certificates valid for much over a year.
    assert lifetime <= datetime.timedelta(days=399)


def test_covers_is_false_for_an_address_not_in_the_certificate(tmp_path):
    cert_path, _ = certs.generate(["192.168.1.20"], tmp_path)
    assert not certs.covers(cert_path, ["192.168.1.99"])


def test_ensure_reuses_a_matching_certificate(tmp_path):
    cert_path, _ = certs.ensure(["192.168.1.20"], tmp_path)
    first = cert_path.read_bytes()
    again, _ = certs.ensure(["192.168.1.20"], tmp_path)
    assert again.read_bytes() == first


def test_ensure_regenerates_when_the_lan_address_changes(tmp_path):
    """A new DHCP lease must not silently leave a certificate for the old IP."""
    cert_path, _ = certs.ensure(["192.168.1.20"], tmp_path)
    first = cert_path.read_bytes()
    changed, _ = certs.ensure(["192.168.1.55"], tmp_path)
    assert changed.read_bytes() != first
    assert certs.covers(changed, ["192.168.1.55"])


def test_covers_handles_a_missing_or_corrupt_certificate(tmp_path):
    assert not certs.covers(tmp_path / "nope.pem", ["127.0.0.1"])
    broken = tmp_path / "broken.pem"
    broken.write_text("not a certificate", encoding="utf-8")
    assert not certs.covers(broken, ["127.0.0.1"])


def test_hostnames_are_accepted_alongside_ip_addresses(tmp_path):
    cert_path, _ = certs.generate(["darts-pc.local"], tmp_path)
    assert certs.covers(cert_path, ["darts-pc.local", "localhost"])

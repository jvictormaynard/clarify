"""Reusable computer relay fixtures. This module defines no test cases."""

import asyncio


from datetime import datetime, timedelta, timezone


import ssl


from cryptography import x509

from cryptography.hazmat.primitives import hashes, serialization

from cryptography.hazmat.primitives.asymmetric import ec

from cryptography.x509.oid import NameOID


from computer_relay_protocol import (
    RelayIdentity,
)


HOST = "relay.test"


def make_certificate(name, *, ca=None, ca_key=None, is_ca=False, curve=None):
    key = ec.generate_private_key(curve or ec.SECP256R1())
    subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, name)])
    now = datetime.now(timezone.utc)
    builder = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(ca.subject if ca else subject)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(days=1))
        .not_valid_after(now + timedelta(days=2))
        .add_extension(
            x509.BasicConstraints(ca=is_ca, path_length=0 if is_ca else None),
            critical=True,
        )
        .add_extension(
            x509.SubjectAlternativeName([x509.DNSName(name)]), critical=False
        )
    )
    if is_ca:
        builder = builder.add_extension(
            x509.KeyUsage(
                digital_signature=True,
                content_commitment=False,
                key_encipherment=False,
                data_encipherment=False,
                key_agreement=False,
                key_cert_sign=True,
                crl_sign=True,
                encipher_only=None,
                decipher_only=None,
            ),
            critical=True,
        )
    return key, builder.sign(ca_key or key, hashes.SHA256())


def server_context(directory, name, key, cert):
    cert_path, key_path = directory / (name + ".crt"), directory / (name + ".key")
    cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    key_path.write_bytes(
        key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    context.load_cert_chain(cert_path, key_path)
    return context


def client_context(cert, *, check_hostname=True):
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    context.check_hostname = check_hostname
    context.load_verify_locations(
        cadata=cert.public_bytes(serialization.Encoding.PEM).decode("ascii")
    )
    return context


def identity(key, cert):
    return RelayIdentity(
        cert.public_bytes(serialization.Encoding.DER),
        lambda message: key.sign(message, ec.ECDSA(hashes.SHA256())),
    )


async def eventually(predicate, timeout=4):
    async with asyncio.timeout(timeout):
        while not predicate():
            await asyncio.sleep(0.01)

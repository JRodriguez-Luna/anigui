"""Release signatures: AniGUI only installs updates signed by its publisher.

The publisher's private key never leaves their Mac (it lives in the macOS
Keychain, see core/signer.py). Only the public half is built into the app, here.
A signature covers the version *and* the file's SHA-256, so an old signed
release can't be passed off as a newer one.
"""

from __future__ import annotations

import base64
import binascii

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey

# Base64 Ed25519 public keys allowed to sign AniGUI releases. Adding a second key
# here (in a release signed by the first) is how the key would be rotated.
PUBLIC_KEYS: tuple[str, ...] = (
    "6a0BF+EDyjWfnnMwWfUc5JTLZZ7tFuxJ1JOWeFZohSQ=",   # JRodriguez-Luna, created Nov 1, 2026
)

CONTEXT = b"AniGUI release signature v1"


def message(version: str, sha256: str) -> bytes:
    return b"\n".join((CONTEXT, version.strip().encode(), sha256.strip().lower().encode()))


def enforced(keys: tuple[str, ...] | None = None) -> bool:
    """Signatures are required as soon as a publisher key is built in."""
    return bool(PUBLIC_KEYS if keys is None else keys)


def verify(version: str, sha256: str, signature_b64: str, keys: tuple[str, ...] | None = None) -> bool:
    try:
        signature = base64.b64decode(signature_b64.strip(), validate=True)
    except (binascii.Error, ValueError):
        return False
    msg = message(version, sha256)
    for key in (PUBLIC_KEYS if keys is None else keys):
        try:
            Ed25519PublicKey.from_public_bytes(base64.b64decode(key)).verify(signature, msg)
            return True
        except (InvalidSignature, ValueError, binascii.Error):
            continue
    return False


# -- publisher side (used by core/signer.py on the publisher's Mac) ---------------------

def new_private_key() -> str:
    from cryptography.hazmat.primitives import serialization
    raw = Ed25519PrivateKey.generate().private_bytes(
        serialization.Encoding.Raw, serialization.PrivateFormat.Raw, serialization.NoEncryption())
    return base64.b64encode(raw).decode()


def public_key_of(private_b64: str) -> str:
    from cryptography.hazmat.primitives import serialization
    key = Ed25519PrivateKey.from_private_bytes(base64.b64decode(private_b64))
    raw = key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    return base64.b64encode(raw).decode()


def sign(private_b64: str, version: str, sha256: str) -> str:
    key = Ed25519PrivateKey.from_private_bytes(base64.b64decode(private_b64))
    return base64.b64encode(key.sign(message(version, sha256))).decode()

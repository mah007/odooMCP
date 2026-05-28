"""Fernet symmetric encryption for storing Odoo credentials at rest."""

import base64
import os

from cryptography.fernet import Fernet


def _get_fernet() -> Fernet:
    secret = os.environ.get("SECRET_KEY", "")
    if not secret:
        raise RuntimeError("SECRET_KEY environment variable is not set")
    # Derive a 32-byte key from SECRET_KEY via base64
    key_bytes = secret.encode()[:32].ljust(32, b"0")
    return Fernet(base64.urlsafe_b64encode(key_bytes))


def encrypt_credential(plaintext: str) -> str:
    return _get_fernet().encrypt(plaintext.encode()).decode()


def decrypt_credential(ciphertext: str) -> str:
    return _get_fernet().decrypt(ciphertext.encode()).decode()

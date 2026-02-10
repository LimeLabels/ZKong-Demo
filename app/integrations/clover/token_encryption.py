"""
Clover token encryption at rest (Fernet).
When clover_token_encryption_key is set, encrypt/decrypt clover_access_token and clover_refresh_token
in store_mappings.metadata so DB compromise does not expose plaintext tokens.
"""

from typing import Any, Dict, Optional

from cryptography.fernet import Fernet, InvalidToken
import structlog

from app.config import settings

logger = structlog.get_logger()

CLOVER_TOKEN_KEYS = ("clover_access_token", "clover_refresh_token")


def _get_fernet() -> Optional[Fernet]:
    """Return Fernet instance if encryption key is configured; else None."""
    key = getattr(settings, "clover_token_encryption_key", None) or ""
    if not key or not key.strip():
        return None
    key = key.strip()
    if len(key) != 44:  # Fernet key is 44 bytes base64
        logger.warning(
            "clover_token_encryption_key must be a 44-char Fernet key; encryption disabled",
            key_len=len(key),
        )
        return None
    try:
        return Fernet(key.encode("utf-8"))
    except Exception as e:
        logger.warning("Invalid clover_token_encryption_key; encryption disabled", error=str(e))
        return None


def encrypt_tokens_for_storage(metadata: Dict[str, Any]) -> Dict[str, Any]:
    """
    Return a copy of metadata with clover_access_token and clover_refresh_token
    encrypted. If encryption is not configured, return a copy unchanged.
    """
    out = dict(metadata)
    fernet = _get_fernet()
    if not fernet:
        return out
    for key in CLOVER_TOKEN_KEYS:
        val = out.get(key)
        if val and isinstance(val, str):
            try:
                out[key] = fernet.encrypt(val.encode("utf-8")).decode("ascii")
            except Exception as e:
                logger.warning("Clover token encryption failed", key=key, error=str(e))
    return out


def decrypt_tokens_from_storage(metadata: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Return a copy of metadata with clover_access_token and clover_refresh_token
    decrypted. If encryption is not configured or value is not encrypted, return copy with values as-is.
    InvalidToken (e.g. plaintext) is treated as backward compat: leave value unchanged.
    """
    if not metadata:
        return {}
    out = dict(metadata)
    fernet = _get_fernet()
    if not fernet:
        return out
    for key in CLOVER_TOKEN_KEYS:
        val = out.get(key)
        if val and isinstance(val, str):
            try:
                out[key] = fernet.decrypt(val.encode("ascii")).decode("utf-8")
            except InvalidToken:
                # Plaintext (e.g. before migration or key not set when written)
                pass
            except Exception as e:
                logger.warning("Clover token decryption failed", key=key, error=str(e))
    return out

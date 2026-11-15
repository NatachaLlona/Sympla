from cryptography.fernet import Fernet, InvalidToken
from django.conf import settings


class ProviderSecretError(Exception):
    pass


def cipher():
    try:
        return Fernet(settings.PROVIDER_ENCRYPTION_KEY.encode("ascii"))
    except (ValueError, UnicodeError):
        raise ProviderSecretError("Provider encryption key is unavailable.") from None


def encrypt_token(value):
    if (
        not isinstance(value, str)
        or not value.strip()
        or len(value) > 4096
        or any(ord(c) < 33 or ord(c) > 126 for c in value)
    ):
        raise ValueError(
            "A nonempty Sympla token with printable characters is required."
        )
    return cipher().encrypt(value.encode()).decode()


def decrypt_token(user):
    if not user.sympla_token_encrypted:
        return ""
    try:
        return cipher().decrypt(user.sympla_token_encrypted.encode()).decode()
    except (InvalidToken, ValueError, UnicodeError):
        raise ProviderSecretError("Provider token cannot be decrypted.") from None

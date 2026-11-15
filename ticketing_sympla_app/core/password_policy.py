import string

PASSWORD_RULES = (
    "Password must contain 8 to 16 characters, including at least one uppercase letter, "
    "one lowercase letter, one digit and one special character. "
    "Use printable ASCII characters; spaces are not allowed."
)


def valid_password(value):
    return (
        isinstance(value, str)
        and 8 <= len(value) <= 16
        and all(33 <= ord(c) <= 126 for c in value)
        and any(c in string.ascii_uppercase for c in value)
        and any(c in string.ascii_lowercase for c in value)
        and any(c in string.digits for c in value)
        and any(c in string.punctuation for c in value)
    )

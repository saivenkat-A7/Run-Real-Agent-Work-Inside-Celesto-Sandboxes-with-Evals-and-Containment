import secrets
import string

_ALPHABET = string.ascii_lowercase + string.digits


def new_sandbox_name() -> str:
    """sbx- + 10 random [a-z0-9] (~51 bits): collision-free even across concurrent jobs."""
    return "sbx-" + "".join(secrets.choice(_ALPHABET) for _ in range(10))

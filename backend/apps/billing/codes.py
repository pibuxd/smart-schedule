"""Free-access codes: generating, normalizing and hashing. Only the hash and the first 4 characters are stored."""

import hashlib
import secrets

# No 0/O, 1/I/L: the code is read from a message and typed by hand.
ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"
CODE_LENGTH = 12
PREFIX_LENGTH = 4


def generate_code() -> str:
    return "".join(secrets.choice(ALPHABET) for _ in range(CODE_LENGTH))


def format_code(code: str) -> str:
    """ABCD-EFGH-JKMN: easier to read aloud and retype."""
    return "-".join(code[i : i + 4] for i in range(0, len(code), 4))


def normalize_code(raw: str) -> str:
    """Case, spaces and dashes do not matter."""
    return "".join(ch for ch in str(raw).upper() if ch.isalnum())


def hash_code(code: str) -> str:
    # A plain SHA-256 is enough: the code is random with about 59 bits, so it cannot be guessed from the hash,
    # and (unlike a keyed hash) it keeps working when SECRET_KEY is rotated.
    return hashlib.sha256(normalize_code(code).encode()).hexdigest()

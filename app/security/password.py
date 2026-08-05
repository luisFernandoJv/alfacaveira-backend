"""Hash e verificação de senha (Argon2)."""

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError

_hasher = PasswordHasher()


def hash_password(plain_password: str) -> str:
    """Gera o hash Argon2 de uma senha em texto puro."""
    return _hasher.hash(plain_password)


def verify_password(plain_password: str, password_hash: str) -> bool:
    """Verifica se a senha em texto puro corresponde ao hash armazenado."""
    try:
        return _hasher.verify(password_hash, plain_password)
    except VerifyMismatchError:
        return False

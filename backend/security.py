import bcrypt

MAX_BCRYPT_BYTES = 72


def _prepare(password: str) -> bytes:
    # bcrypt only uses the first 72 bytes. Cut explicitly, as passlib did, so
    # existing hashes keep verifying and newer bcrypt versions do not raise an error.
    return password.encode("utf-8")[:MAX_BCRYPT_BYTES]


def hash_password(plain_password: str) -> str:
    return bcrypt.hashpw(_prepare(plain_password), bcrypt.gensalt()).decode("utf-8")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    try:
        return bcrypt.checkpw(_prepare(plain_password), hashed_password.encode("utf-8"))
    except ValueError:
        return False

"""Minimal base58 (Bitcoin alphabet) for 32-byte pubkeys. No extra dependency."""
_ALPHABET = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
_INDEX = {c: i for i, c in enumerate(_ALPHABET)}


def b58encode(raw: bytes) -> str:
    zeros = 0
    for byte in raw:
        if byte == 0:
            zeros += 1
        else:
            break
    number = int.from_bytes(raw, "big") if raw else 0
    chars: list[str] = []
    while number:
        number, rem = divmod(number, 58)
        chars.append(_ALPHABET[rem])
    return ("1" * zeros) + ("".join(reversed(chars)) if chars else "")


def b58decode(text: str) -> bytes:
    zeros = 0
    for char in text:
        if char == "1":
            zeros += 1
        else:
            break
    number = 0
    for char in text:
        try:
            number = number * 58 + _INDEX[char]
        except KeyError as exc:
            raise ValueError(f"invalid base58 character {char!r}") from exc
    body = number.to_bytes((number.bit_length() + 7) // 8, "big") if number else b""
    return b"\x00" * zeros + body


def b58encode_pubkey(raw: bytes) -> str:
    if len(raw) != 32:
        raise ValueError("pubkey must be 32 bytes")
    return b58encode(raw)


def b58decode_pubkey(text: str) -> bytes:
    raw = b58decode(text)
    if len(raw) > 32:
        raise ValueError("pubkey longer than 32 bytes")
    return b"\x00" * (32 - len(raw)) + raw

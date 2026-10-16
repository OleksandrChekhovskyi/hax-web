from __future__ import annotations


def sanitize_text(value: object) -> str:
    if not isinstance(value, str):
        return ""
    return "".join(
        char
        for char in value
        if char in "\n\t"
        or (
            ord(char) >= 32
            and not 127 <= ord(char) <= 159
            and not 0xD800 <= ord(char) <= 0xDFFF
        )
    )

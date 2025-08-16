from typing import Any

try:
    import tiktoken

    _ENC: Any = tiktoken.get_encoding("cl100k_base")
except Exception:
    _ENC = None


def count_tokens(texts: list[str]) -> int:
    enc = _ENC
    if enc is None:
        # fallback rough estimate
        return sum(max(1, len(t) // 4) for t in texts)
    # concatenate isn't necessary; count individually for memory
    n = 0
    for t in texts:
        try:
            n += len(enc.encode(t))
        except Exception:
            n += max(1, len(t) // 4)
    return n

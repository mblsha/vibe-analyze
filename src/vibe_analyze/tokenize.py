from typing import List

_ENC = None


def _load_enc():
    global _ENC
    if _ENC is not None:
        return _ENC
    try:
        import tiktoken  # type: ignore

        _ENC = tiktoken.get_encoding("cl100k_base")
    except Exception:
        _ENC = None
    return _ENC


def count_tokens(texts: List[str]) -> int:
    enc = _load_enc()
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

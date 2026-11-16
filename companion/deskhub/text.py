"""The hub's fonts only cover ASCII, so text sent to it is folded down."""
import unicodedata

_REPLACE = {
    "‘": "'", "’": "'", "“": '"', "”": '"',
    "–": "-", "—": "-", "…": "...", "·": "-", "•": "-",
}


def ascii_fold(s: str | None, limit: int = 120) -> str:
    if not s:
        return ""
    s = "".join(_REPLACE.get(c, c) for c in s)
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode("ascii")
    s = " ".join(s.split())
    return s[:limit]

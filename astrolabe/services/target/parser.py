import re


_BAYER_RE = re.compile(
    r"^(alpha|beta|gamma|delta|epsilon|zeta|eta|theta|iota|kappa|lambda|mu|nu|xi|omicron|pi|rho|sigma|tau|upsilon|phi|chi|psi|omega)([a-z]{1,3})$"
)
_FLAMSTEED_RE = re.compile(r"^([0-9]{1,3})([a-z]{2,3})$")


def parse_bayer_flamsteed(value: str) -> str | None:
    match = _BAYER_RE.match(value)
    if match:
        return f"{match.group(1)} {match.group(2)}"
    match = _FLAMSTEED_RE.match(value)
    if match:
        return f"{match.group(1)} {match.group(2)}"
    return None

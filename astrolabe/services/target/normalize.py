import re


_NON_ALNUM = re.compile(r"[^a-z0-9]+")

_GREEK_MAP = {
    "\u03bc": "mu",
    "\u03b1": "alpha",
    "\u03b2": "beta",
    "\u03b3": "gamma",
    "\u03b4": "delta",
    "\u03b5": "epsilon",
    "\u03b6": "zeta",
    "\u03b7": "eta",
    "\u03b8": "theta",
    "\u03b9": "iota",
    "\u03ba": "kappa",
    "\u03bb": "lambda",
    "\u03bd": "nu",
    "\u03be": "xi",
    "\u03bf": "omicron",
    "\u03c0": "pi",
    "\u03c1": "rho",
    "\u03c3": "sigma",
    "\u03c4": "tau",
    "\u03c5": "upsilon",
    "\u03c6": "phi",
    "\u03c7": "chi",
    "\u03c8": "psi",
    "\u03c9": "omega",
}


def normalize_query(value: str) -> str:
    value = value.strip().lower()
    for greek, ascii_name in _GREEK_MAP.items():
        value = value.replace(greek, ascii_name)
    value = _NON_ALNUM.sub("", value)
    return value

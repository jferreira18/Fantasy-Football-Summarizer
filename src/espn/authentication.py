"""Cookie authentication; values must never be logged."""


def cookie_header(espn_s2: str, swid: str) -> str:
    if bool(espn_s2) != bool(swid):
        raise ValueError("Both ESPN_S2 and ESPN_SWID are required for private leagues")
    if any(char in espn_s2 + swid for char in "\r\n;"):
        raise ValueError("Invalid ESPN cookie format")
    return f"espn_s2={espn_s2}; SWID={swid}" if espn_s2 else ""

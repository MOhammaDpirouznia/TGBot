"""
TGBot Version Information
Canonical single source of truth for the installed system version.
"""

__version__ = "3.28.0"
__build__ = "2026.09.25"
__channel__ = "stable"
__product_name__ = "TGBot"


def get_version() -> str:
    """Return normalized version string (e.g. 'v3.28.0')"""
    v = __version__.strip()
    return v if v.startswith("v") else f"v{v}"


def get_version_info() -> dict:
    return {
        "version": get_version(),
        "raw_version": __version__,
        "build": __build__,
        "channel": __channel__,
        "product_name": __product_name__,
    }

"""
Authorship credit for the panel.

The name, year and link live here — server-side — and reach the browser only
at runtime via /api/meta. The built frontend bundle carries no copy of them,
so editing or rebuilding the static assets cannot change what is shown; the
string has to come from this file.

Rendered by frontend/src/credit.js, which mounts it outside the React root and
restores it if it is removed from the DOM.
"""

AUTHOR_NAME = "ALI HAMZA"
AUTHOR_URL = "https://www.linkedin.com/in/alihamza053/"
AUTHOR_YEAR = "2026"


def credit() -> dict:
    """The credit as structured fields — the frontend composes the markup so
    nothing here is ever interpolated into HTML as a raw string."""
    return {
        "prefix": "Created by",
        "name": AUTHOR_NAME,
        "url": AUTHOR_URL,
        "year": AUTHOR_YEAR,
    }

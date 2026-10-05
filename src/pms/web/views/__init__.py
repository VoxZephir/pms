"""Routes, one module per page.

Everything hangs off one window: `?from=&to=&grain=`. Fragments are served by
the same handlers as the full page, so the JavaScript enhancement (swap `<main>`
instead of reloading) and the no-JavaScript path render identical markup.

`common` holds the blueprint and what every page shares; each other module
registers its routes on import, which is what the imports below are for.
"""

from . import (  # noqa: F401
               analyse,
               corrections,
               dashboard,
               previsions,
               system,
               transactions,
)
from .common import bp

__all__ = ["bp"]

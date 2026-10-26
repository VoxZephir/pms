"""What the JSON API (`web/api/`) builds on, and the few routes that are not
a page: the files handed out (`exports`), health and re-ingestion
(`system`), the reclassification endpoints (`corrections`).

`common` holds the blueprint, the store and what every view shares -- the
view switches carried in the URL, the table's filter and sort; `savings` and
`previsions` hold the arithmetic of their pages. Each module registers its
routes on import, which is what the imports below are for.
"""

from . import (  # noqa: F401
               corrections,
               exports,
               previsions,
               system,
)
from .common import bp

__all__ = ["bp"]

"""Which colour slot a category takes.

The eight categorical slots are validated (contrast and colour vision, both
themes; the values live in the front end's styles.css). Colour follows the
entity: the mapping is fixed once per window, by total spend, and every chart
of the window reuses it so a category keeps its hue everywhere. Never cycle --
a ninth hue would be indistinguishable from the first: the tail folds into
`Autres`.
"""

from __future__ import annotations

from ..analysis import OTHER

MAX_SLOTS = 8


def colour_map(categories: list[dict]) -> tuple[dict[str, int], list[dict]]:
    """Fixed hue per category for this window; the tail folds into `Autres`.

    Recomputed per window on purpose: a category that does not appear in the
    window should not hold a slot. The cost is that a hue can mean a different
    category in a different window, which is why the legend is always present.
    """
    named = [c["category"] for c in categories][:MAX_SLOTS - 1]
    slots = {name: i for i, name in enumerate(named)}
    slots[OTHER] = len(named)
    legend = [{"name": n, "slot": slots[n]} for n in named + [OTHER]]
    return slots, legend

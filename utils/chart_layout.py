"""
Shared collision layout for the feasibility/business-value opportunity
quadrant chart, used identically by the Streamlit UI (Opportunity Studio,
Plotly) and the client PDF (utils/pdf_report.py, matplotlib) so both
render the same picture.

Root cause this fixes: opportunity scoring is deterministic and coarse
(integer 1-5 scales), so it's common for several opportunities to land on
the exact same (feasibility, business_value) point. Plotted naively, their
markers stack exactly on top of each other and their text labels overwrite
each other into unreadable overlapping text — which is what was reported.
This spreads exact-duplicate points around a small circle so every marker
and label is visible, while each item's ORIGINAL (un-jittered) score is
still what's shown in hover text / tables — the jitter is a display-only
layout fix, never a change to the underlying data.
"""
from __future__ import annotations
import math
from collections import defaultdict


def jitter_quadrant_points(items, x_attr: str = "feasibility", y_attr: str = "business_value", radius: float = 0.32):
    """
    Returns a list of dicts: {"item": obj, "x": float, "y": float, "label_above": bool}
    x/y are display coordinates (jittered apart when tied); label_above
    alternates so stacked labels don't sit on the same side of the marker.
    """
    groups: dict[tuple, list] = defaultdict(list)
    for it in items:
        groups[(getattr(it, x_attr), getattr(it, y_attr))].append(it)

    out = []
    for (fx, fy), group in groups.items():
        n = len(group)
        for i, it in enumerate(group):
            if n == 1:
                x, y = float(fx), float(fy)
            else:
                angle = (2 * math.pi * i / n) + math.pi / 2  # start pointing up
                x = fx + radius * math.cos(angle)
                y = fy + radius * math.sin(angle)
                x = min(max(x, 0.15), 5.85)
                y = min(max(y, 0.15), 5.85)
            out.append({"item": it, "x": x, "y": y, "label_above": (i % 2 == 0)})
    return out


def tied_groups_note(items, x_attr: str = "feasibility", y_attr: str = "business_value") -> str:
    """
    A one-line, honest interpretation note when 2+ opportunities share
    identical coordinates — a real signal that the scoring axes aren't
    differentiating those items, not just a chart cosmetic issue.
    """
    groups: dict[tuple, list] = defaultdict(list)
    for it in items:
        groups[(getattr(it, x_attr), getattr(it, y_attr))].append(it)
    tied = [g for g in groups.values() if len(g) > 1]
    if not tied:
        return ""
    parts = []
    for g in tied:
        names = ", ".join(o.name for o in g)
        parts.append(f"{names} (feasibility {getattr(g[0], x_attr)}, value {getattr(g[0], y_attr)})")
    return (
        f"{len(tied)} group(s) of opportunities share identical feasibility/value scores — "
        + "; ".join(parts)
        + ". Their relative ranking on this chart comes from the small jitter applied for "
        "readability, not a real difference in scores; use the Priority column in the table "
        "above (which also weighs data readiness and time-to-value) to break ties, or refine "
        "the underlying scoring if finer-grained differentiation is needed."
    )

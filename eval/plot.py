"""Operating-point chart (T3): accuracy and normal false-positive rate vs min_top_score on seed range B.

Palette: categorical slots 1-2 of the dataviz reference palette (validated light mode: CVD ΔE 24.7, normal 33.6).
One y-axis (both series are rates in [0, 1]); direct labels + legend; recessive grid.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

from netcoop.config import ROOT  # noqa: E402

OUT = ROOT / "docs" / "operating_point.png"
SURFACE, INK, INK2, GRID = "#fcfcfb", "#0b0b0b", "#52514e", "#e1e0d9"
S1, S2 = "#2a78d6", "#eb6834"


def operating_point_chart(rows: list[dict[str, Any]], chosen: float | None, out: Path = OUT) -> Path:
    xs = [r["min_top_score"] for r in rows]
    acc = [r["accuracy"] for r in rows]
    fp = [r["false_positive_rate_normal"] for r in rows]
    fig, ax = plt.subplots(figsize=(8, 4.5), dpi=150)
    fig.patch.set_facecolor(SURFACE)
    ax.set_facecolor(SURFACE)
    ax.plot(xs, acc, color=S1, lw=2, marker="o", ms=8, mec=SURFACE, mew=2, label="Accuracy (all incidents)", zorder=3)
    ax.plot(xs, fp, color=S2, lw=2, marker="s", ms=8, mec=SURFACE, mew=2, label="False-positive rate on normal", zorder=3)
    ax.axhline(0.05, color=INK2, lw=1, ls=":", zorder=1)
    ax.text(xs[-1], 0.05 + 0.015, "FP limit 5 %", color=INK2, fontsize=8, ha="right")
    if chosen is not None and chosen in xs:
        i = xs.index(chosen)
        ax.axvline(chosen, color=INK2, lw=1, ls="--", zorder=1)
        ax.annotate(f"chosen on seed A: {chosen:.2f}\naccuracy {acc[i]:.2f}, FP {fp[i]:.2f}",
                    xy=(chosen, acc[i]), xytext=(10, -42), textcoords="offset points", color=INK, fontsize=9)
    ax.text(xs[-1] + 0.008, acc[-1], "accuracy", color=INK, fontsize=9, va="center")
    ax.text(xs[-1] + 0.008, fp[-1], "normal FP", color=INK, fontsize=9, va="center")
    ax.set_xlim(xs[0] - 0.02, xs[-1] + 0.07)
    ax.set_ylim(0, 1)
    ax.set_xticks(xs)
    ax.set_xlabel("min_top_score (status threshold)", color=INK2)
    ax.set_ylabel("rate", color=INK2)
    ax.set_title("Operating point sweep, held-out seed range B", color=INK, loc="left", fontsize=11)
    ax.grid(axis="y", color=GRID, lw=0.8)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    for side in ("left", "bottom"):
        ax.spines[side].set_color(GRID)
    ax.tick_params(colors=INK2, labelsize=8)
    leg = ax.legend(loc="center left", frameon=False, fontsize=8)
    for t in leg.get_texts():
        t.set_color(INK)
    fig.tight_layout()
    out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out, facecolor=SURFACE)
    plt.close(fig)
    return out

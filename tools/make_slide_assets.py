"""Slide asset pack: reads eval/reports/* ONLY and writes docs/slides/*.png (1920x1080, one message per chart).

    .venv/Scripts/python tools/make_slide_assets.py

Palette: dataviz reference categorical slots 1-3 (blue #2a78d6, orange #eb6834, aqua #1baf7a), validated for the
light surface (adjacent CVD dE >= 9.2, normal-vision dE >= 27.6). Aqua is below 3:1 contrast, so every series is
direct-labelled and has its own marker / line style (secondary encoding). One y-axis per chart, recessive grid,
text in ink colors (never series colors).
"""

from __future__ import annotations

import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
REP = ROOT / "eval" / "reports"
OUT = ROOT / "docs" / "slides"
SURFACE, INK, INK2, GRID = "#fcfcfb", "#0b0b0b", "#52514e", "#e1e0d9"
BLUE, ORANGE, AQUA = "#2a78d6", "#eb6834", "#1baf7a"
W, H, DPI = 19.2, 10.8, 100  # 1920 x 1080

plt.rcParams.update({"font.size": 26, "font.family": "DejaVu Sans", "axes.edgecolor": GRID, "axes.labelcolor": INK2,
                     "xtick.color": INK2, "ytick.color": INK2, "xtick.labelsize": 24, "ytick.labelsize": 24,
                     "axes.titlesize": 40, "axes.titleweight": "bold", "axes.titlecolor": INK, "legend.fontsize": 24})


def load(name: str) -> dict:
    return json.loads((REP / name).read_text(encoding="utf-8"))


def fig_ax(title: str, subtitle: str):
    fig, ax = plt.subplots(figsize=(W, H), dpi=DPI)
    fig.patch.set_facecolor(SURFACE)
    ax.set_facecolor(SURFACE)
    fig.subplots_adjust(left=0.09, right=0.86, top=0.80, bottom=0.13)
    fig.text(0.09, 0.93, title, fontsize=44, fontweight="bold", color=INK, ha="left", va="center")
    fig.text(0.09, 0.865, subtitle, fontsize=24, color=INK2, ha="left", va="center")
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)
    ax.grid(axis="y", color=GRID, lw=1)
    ax.set_axisbelow(True)
    return fig, ax


def save(fig, name: str) -> Path:
    OUT.mkdir(parents=True, exist_ok=True)
    p = OUT / name
    fig.savefig(p, facecolor=SURFACE)
    plt.close(fig)
    return p


def end_label(ax, x, y, text, dy=0.0):
    ax.annotate(text, xy=(x, y), xytext=(14, dy), textcoords="offset points", va="center", color=INK, fontsize=24)


# 1 ------------------------------------------------------------------------------------------------------------
def accuracy_per_fault() -> Path:
    b = load("eval_B.json")["per_fault"]
    o = load("organizer.json")["B"]["per_label"]
    rows = [(k.replace("_", " ") + (" (ours)" if k == "normal" else ""), v["accuracy"], "ours", v["n"]) for k, v in b.items()]
    rows += [(k.replace("_", " ") + (" (organizer)" if k == "normal" else ""), v["accuracy"], "org", v["n"])
             for k, v in o.items()]
    rows.sort(key=lambda r: (r[2] != "org", -r[1], r[0]))
    fig, ax = fig_ax("Accuracy per fault on held-out data",
                     "Held-out seeds. Organizer generator: 500 per label. NetCoop generator: 280 incidents.")
    ax.grid(axis="y", visible=False)
    ax.grid(axis="x", color=GRID, lw=1)
    ys = list(range(len(rows)))[::-1]
    for y, (name, acc, src, _n) in zip(ys, rows, strict=True):
        color = ORANGE if src == "org" else BLUE
        ax.barh(y, acc, height=0.62, color=color, edgecolor=SURFACE, linewidth=2)
        ax.text(acc + 0.01, y, f"{acc:.0%}", va="center", color=INK, fontsize=24)
        ax.text(-0.01, y, f"{name}", va="center", ha="right", color=INK, fontsize=24)
    ax.set_yticks([])
    ax.set_xlim(0, 1.08)
    ax.set_xticks([0, 0.25, 0.5, 0.75, 1.0])
    ax.set_xticklabels(["0%", "25%", "50%", "75%", "100%"])
    ax.spines["left"].set_visible(False)
    fig.subplots_adjust(left=0.22, top=0.76)
    from matplotlib.patches import Patch
    fig.legend(handles=[Patch(color=ORANGE, label="Organizer generator"), Patch(color=BLUE, label="NetCoop generator")],
               loc="upper right", bbox_to_anchor=(0.86, 0.84), ncol=2, frameon=False)
    return save(fig, "1_accuracy_per_fault.png")


# 2 ------------------------------------------------------------------------------------------------------------
def degradation() -> Path:
    ours = load("fuzz.json")
    org = load("organizer_robustness.json")["corruption"]
    x1 = [p["corruption_rate"] * 100 for p in ours]
    x2 = [p["corruption_rate"] * 100 for p in org]
    a_ours = [p["accuracy"] for p in ours]
    a_org = [p["accuracy"] for p in org]
    a_off = [p["accuracy_without_registry"] for p in ours]
    fig, ax = fig_ax("Corrupted input barely moves accuracy",
                     "Records corrupted at random (renamed fields, swapped units, legacy v0.9, mangled IDs, missing values)")
    ax.plot(x2, a_org, color=ORANGE, lw=3, marker="s", ms=13, mec=SURFACE, mew=2, label="Organizer data")
    ax.plot(x1, a_ours, color=BLUE, lw=3, marker="o", ms=13, mec=SURFACE, mew=2, label="NetCoop generator")
    ax.plot(x1, a_off, color=AQUA, lw=3, ls="--", marker="^", ms=13, mec=SURFACE, mew=2,
            label="NetCoop generator, alias/unit registry OFF")
    end_label(ax, x2[-1], a_org[-1], f"organizer {a_org[-1]:.2f}", dy=14)
    end_label(ax, x1[-1], a_ours[-1], f"ours {a_ours[-1]:.2f}", dy=-14)
    end_label(ax, x1[-1], a_off[-1], f"registry off {a_off[-1]:.2f}")
    ax.set_xlim(-2, 75)
    ax.set_ylim(0, 1.05)
    ax.set_xticks([0, 10, 20, 30, 40, 50, 60])
    ax.set_xticklabels([f"{v}%" for v in (0, 10, 20, 30, 40, 50, 60)])
    ax.set_xlabel("share of records corrupted")
    ax.set_ylabel("accuracy")
    ax.legend(loc="lower left", frameon=False)
    return save(fig, "2_degradation_curve.png")


# 3 ------------------------------------------------------------------------------------------------------------
def severity_sweep() -> Path:
    rob = load("organizer_robustness.json")["severity"]
    weak = load("weak_hw_after.json")
    lv = [0.25, 0.5, 0.75, 1.0]
    x = [v * 100 for v in lv]
    sev = {(r["label"], r["level"]): r for r in rob}
    lat = [sev[("latency_spike", v)]["correct"] for v in lv]
    hw = [sev[("hardware_failure", v)]["correct"] for v in lv]
    top2 = []
    for v in lv:
        rows = weak["incidents"][str(v)]
        top2.append(sum(1 for r in rows if r["rank"] is not None and r["rank"] <= 2) / len(rows))
    fig, ax = fig_ax("Weakened faults stay in the top-2 causes",
                     "Organizer generator wrapped, not edited. Fault strength scaled 25-100%. 200 held-out seeds per point.")
    ax.plot(x, top2, color=AQUA, lw=3, ls="--", marker="^", ms=14, mec=SURFACE, mew=2,
            label="hardware failure in top-2 causes")
    ax.plot(x, hw, color=BLUE, lw=3, marker="o", ms=14, mec=SURFACE, mew=2, label="hardware failure correct (top cause)")
    ax.plot(x, lat, color=ORANGE, lw=3, marker="s", ms=14, mec=SURFACE, mew=2, label="latency spike correct")
    end_label(ax, x[0], top2[0], f"{top2[0]:.0%} in top-2", dy=-34)
    ax.annotate(f"{lat[1]:.0%} correct; the rest abstain, never wrong", xy=(x[1], lat[1]), xytext=(16, -40),
                textcoords="offset points", color=INK, fontsize=22)
    ax.set_xlim(18, 108)
    ax.set_ylim(-0.03, 1.08)
    ax.set_xticks(x)
    ax.set_xticklabels([f"{int(v)}%" for v in x])
    ax.set_xlabel("injected fault strength (100% = the organizer's generator as written)")
    ax.set_ylabel("share of incidents")
    fig.subplots_adjust(bottom=0.22)
    fig.legend(loc="lower center", bbox_to_anchor=(0.48, 0.0), ncol=3, frameon=False, fontsize=22)
    return save(fig, "3_severity_sweep.png")


# 4 ------------------------------------------------------------------------------------------------------------
def operating_point() -> Path:
    sw = load("sweep.json")
    rows = sw["B"]
    x = [r["min_top_score"] for r in rows]
    acc = [r["accuracy"] for r in rows]
    fp = [r["false_positive_rate_normal"] for r in rows]
    ch = sw["chosen"]
    fig, ax = fig_ax(f"Operating point {ch:.2f}: zero false alarms",
                     "Picked on seed range A under the three guards; held-out seed range B shown")
    ax.plot(x, acc, color=BLUE, lw=3, marker="o", ms=14, mec=SURFACE, mew=2, label="accuracy (all incidents)")
    ax.plot(x, fp, color=ORANGE, lw=3, marker="s", ms=14, mec=SURFACE, mew=2, label="false-positive rate on normal")
    ax.axhline(0.05, color=INK2, lw=1.5, ls=":")
    ax.text(x[-1], 0.075, "FP limit 5%", color=INK2, ha="right", fontsize=22)
    i = x.index(ch)
    ax.axvline(ch, color=INK2, lw=1.5, ls="--")
    ax.annotate(f"chosen {ch:.2f}\naccuracy {acc[i]:.2f}, FP {fp[i]:.0%}", xy=(ch, acc[i]), xytext=(18, -110),
                textcoords="offset points", color=INK, fontsize=26)
    end_label(ax, x[-1], acc[-1], "accuracy")
    end_label(ax, x[-1], fp[-1], "normal FP", dy=22)
    ax.set_xlim(x[0] - 0.02, x[-1] + 0.08)
    ax.set_ylim(0, 1.0)
    ax.set_xticks(x)
    ax.set_xlabel("min_top_score (how sure before committing to a cause)")
    ax.set_ylabel("rate")
    ax.legend(loc="center left", frameon=False)
    return save(fig, "4_operating_point.png")


# 5 ------------------------------------------------------------------------------------------------------------
def confidence_vs_accuracy() -> Path:
    ours = load("eval_B.json")["calibration"]
    org = load("organizer_robustness.json")["calibration_organizer"]
    fig, ax = fig_ax("Stated confidence vs observed accuracy",
                     "Above the diagonal = conservative. Ours: never overconfident. Organizer: one bin 3.3 points under.")
    ax.plot([0.4, 1.02], [0.4, 1.02], color=INK2, lw=1.5, ls=":")
    ax.text(0.85, 0.79, "stated = observed", color=INK2, fontsize=22)
    ax.plot([c["mean_confidence"] for c in ours], [c["accuracy"] for c in ours], color=BLUE, lw=3, marker="o", ms=16,
            mec=SURFACE, mew=2, label="NetCoop generator (seed B)")
    ax.plot([c["mean_confidence"] for c in org], [c["accuracy"] for c in org], color=ORANGE, lw=3, marker="s", ms=16,
            mec=SURFACE, mew=2, label="Organizer data (all strengths)")
    for c in ours:
        ax.annotate(f"n={c['n']}", xy=(c["mean_confidence"], c["accuracy"]), xytext=(-20, -40), textcoords="offset points",
                    color=INK2, fontsize=20)
    for c in org:
        low = c["mean_confidence"] < 0.9
        ax.annotate(f"said {c['mean_confidence']:.2f}, right {c['accuracy']:.3f} (n={c['n']})",
                    xy=(c["mean_confidence"], c["accuracy"]), xytext=(18, -34) if low else (-470, 26),
                    textcoords="offset points", color=INK, fontsize=22)
    ax.set_xlim(0.4, 1.04)
    ax.set_ylim(0.4, 1.06)
    ax.set_xlabel("stated confidence (bin mean)")
    ax.set_ylabel("observed accuracy")
    ax.legend(loc="lower right", frameon=False)
    return save(fig, "5_confidence_vs_accuracy.png")


def main() -> None:
    for fn in (accuracy_per_fault, degradation, severity_sweep, operating_point, confidence_vs_accuracy):
        print("wrote", fn())


if __name__ == "__main__":
    main()

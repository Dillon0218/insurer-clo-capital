"""Step 6: figures, drawn only from outputs/tables."""
from __future__ import annotations

import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from clo.context import FIGURES, RATINGS, load

# Reference palette, light mode (first three categorical slots validate all-pairs).
SURFACE, INK, INK2, GRID = "#fcfcfb", "#0b0b0b", "#52514e", "#e4e3df"
CLO, CORP, THIRD = "#2a78d6", "#eb6834", "#1baf7a"

plt.rcParams.update({
    "figure.facecolor": SURFACE, "axes.facecolor": SURFACE, "savefig.facecolor": SURFACE,
    "axes.edgecolor": GRID, "axes.labelcolor": INK2, "xtick.color": INK2, "ytick.color": INK2,
    "text.color": INK, "axes.grid": True, "grid.color": GRID, "grid.linewidth": 0.8,
    "axes.spines.top": False, "axes.spines.right": False, "font.size": 10,
    "axes.titlesize": 11, "axes.titleweight": "bold", "legend.frameon": False,
})


def pct(x, d=0):
    return f"{x * 100:.{d}f}%"


def bars(ax, groups, series, colors, labels, fmt, width=0.38):
    x = np.arange(len(groups))
    for i, (vals, c, lab) in enumerate(zip(series, colors, labels)):
        off = (i - (len(series) - 1) / 2) * (width + 0.02)
        ax.bar(x + off, vals, width, color=c, label=lab, zorder=3, edgecolor=SURFACE, linewidth=1)
        for xi, v in zip(x + off, vals):
            ax.text(xi, v, fmt(v), ha="center", va="bottom", fontsize=8, color=INK2)
    ax.set_xticks(x, groups)
    ax.grid(axis="x", visible=False)


def fig_hero() -> None:
    d = load("02_decisions.csv")
    d = d[d["variant"] == "base"].set_index("rating").loc[RATINGS]
    fig, axes = plt.subplots(1, 2, figsize=(11, 4.2))
    bars(axes[0], RATINGS, [d["el_clo"], d["el_corp"]], [CLO, CORP],
         ["CLO tranche", "Corporate bonds, same rating"], lambda v: pct(v, 2))
    axes[0].set_title("Expected loss over 10 years")
    axes[0].yaxis.set_major_formatter(lambda v, _: pct(v, 0))
    bars(axes[1], RATINGS, [d["es_clo"], d["es_corp"]], [CLO, CORP],
         ["CLO tranche", "Corporate bonds, same rating"], lambda v: pct(v, 0))
    axes[1].set_title("Average loss in the worst 0.5% of scenarios (99.5% ES)")
    axes[1].yaxis.set_major_formatter(lambda v, _: pct(v, 0))
    axes[1].set_ylim(0, 1.12)
    axes[0].legend(loc="upper left")
    fig.suptitle("Same rating, similar expected loss, very different tail", x=0.01, ha="left",
                 fontsize=13, fontweight="bold")
    fig.text(0.01, 0.005, "Base model, 100,000 scenarios. Loss = PV shortfall / par. "
             "Corporate = 200 bonds of the tranche's rating on the same economic factor.",
             fontsize=8, color=INK2)
    fig.tight_layout(rect=(0, 0.03, 1, 0.95))
    fig.savefig(FIGURES / "00_hero_el_vs_tail.png", dpi=160)
    plt.close(fig)


def fig_cliff() -> None:
    c = load("02_loss_vs_pool_loss.csv")
    mid = (c["pool_loss_lo"] + c["pool_loss_hi"]) / 2
    fig, axes = plt.subplots(1, 3, figsize=(11, 3.8), sharey=True)
    for ax, r in zip(axes, ["A", "BBB", "BB"]):
        ax.plot(mid, c[f"clo_{r}"], color=CLO, lw=2, label="CLO tranche", zorder=3)
        ax.plot(mid, c[f"corp_{r}"], color=CORP, lw=2, label="Corporate bonds", zorder=3)
        ax.set_title(f"{r}")
        ax.set_xlabel("10-year loss on the loan pool")
        ax.xaxis.set_major_formatter(lambda v, _: pct(v, 0))
    axes[0].yaxis.set_major_formatter(lambda v, _: pct(v, 0))
    axes[0].set_ylabel("Average loss in scenarios with that pool loss")
    axes[0].legend(loc="upper left")
    fig.suptitle("The cliff: a thin tranche goes from nothing to everything", x=0.01, ha="left",
                 fontsize=13, fontweight="bold")
    fig.tight_layout(rect=(0, 0, 1, 0.93))
    fig.savefig(FIGURES / "01_cliff.png", dpi=160)
    plt.close(fig)


def fig_capital() -> None:
    d = load("02_decisions.csv")
    fig, axes = plt.subplots(1, 2, figsize=(11, 4.2), sharey=True)
    for ax, v in zip(axes, d["variant"].unique()):
        g = d[d["variant"] == v].set_index("rating").loc[["AA", "A", "BBB", "BB"]]
        x = np.arange(len(g))
        ax.axhspan(1 / 1.5, 1.5, color=GRID, alpha=0.6, zorder=1, lw=0)
        ax.axhline(1, color=INK2, lw=1, zorder=2)
        ax.scatter(x - 0.1, g["relative_coverage_old"], s=70, color=CORP, zorder=4,
                   label="2021 factors (CLO = corporate)", edgecolor=SURFACE, linewidth=1.5)
        ax.scatter(x + 0.1, g["relative_coverage_new"], s=70, color=CLO, zorder=4,
                   label="2026 CLO factors", edgecolor=SURFACE, linewidth=1.5)
        for xi, a, b in zip(x, g["relative_coverage_old"], g["relative_coverage_new"]):
            ax.annotate("", xy=(xi + 0.1, b), xytext=(xi - 0.1, a),
                        arrowprops=dict(arrowstyle="->", color=INK2, lw=1), zorder=3)
            ax.text(xi + 0.16, b, f"{b:.2f}", fontsize=8, color=INK2, va="center")
        ax.set_yscale("log")
        ax.set_xticks(x, g.index)
        ax.set_title(v if v != "base" else "Base (Gaussian copula)")
        ax.grid(axis="x", visible=False)
    axes[0].set_ylabel("Capital per unit of 99.5% ES,\nCLO tranche / same-rated corporates")
    axes[0].text(-0.45, 1.0, "parity band 0.67-1.5", fontsize=8, color=INK2, va="bottom", ha="left")
    axes[0].set_xlim(-0.5, 3.5)
    axes[1].set_xlim(-0.5, 3.5)
    axes[0].legend(loc="upper left", fontsize=8)
    fig.suptitle("Did the 2026 CLO factors line capital up with tail risk?", x=0.01, ha="left",
                 fontsize=13, fontweight="bold")
    fig.tight_layout(rect=(0, 0, 1, 0.93))
    fig.savefig(FIGURES / "02_capital_coverage.png", dpi=160)
    plt.close(fig)


def fig_recession() -> None:
    r = load("03_recession.csv")
    clo40 = r[(r["instrument"] == "CLO") & r["recovery"].str.startswith("NAIC")].set_index("rating").loc[RATINGS]
    clo62 = r[(r["instrument"] == "CLO") & r["recovery"].str.startswith("Moody")].set_index("rating").loc[RATINGS]
    corp = r[r["instrument"] == "Corporate"].set_index("rating").loc[RATINGS]
    fig, ax = plt.subplots(figsize=(9, 4.2))
    bars(ax, RATINGS, [clo40["pv_loss"], clo62["pv_loss"], corp["pv_loss"]], [CLO, THIRD, CORP],
         ["CLO, NAIC stepdown loan recovery 40%", "CLO, 2008 actual loan recovery 61.7%",
          "Corporate bonds, 2008 recovery 33.8%"], lambda v: pct(v, 0) if v >= 0.005 else "0", width=0.26)
    ax.yaxis.set_major_formatter(lambda v, _: pct(v, 0))
    ax.set_ylim(0, 1.12)
    ax.set_ylabel("PV loss over 10 years")
    ax.legend(loc="upper left", fontsize=8)
    ax.set_title("NAIC 'Similar to 2008' scenario: the recovery assumption decides the BBB and BB answer",
                 loc="left")
    fig.tight_layout()
    fig.savefig(FIGURES / "03_recession.png", dpi=160)
    plt.close(fig)


def fig_sensitivity() -> None:
    d = load("05_sensitivity.csv")
    names = list(dict.fromkeys(d["variant"]))
    fig, axes = plt.subplots(1, 2, figsize=(11, 6.2), sharey=True)
    for ax, r in zip(axes, ["BBB", "BB"]):
        g = d[d["rating"] == r].set_index("variant").loc[names]
        y = np.arange(len(names))[::-1]
        ax.axvspan(1 / 1.5, 1.5, color=GRID, alpha=0.6, lw=0, zorder=1)
        ax.axvline(1, color=INK2, lw=1, zorder=2)
        ax.scatter(g["tail_multiple"], y, s=40, color=CORP, zorder=4, label="Tail multiple (CLO ES / corporate ES)",
                   edgecolor=SURFACE, linewidth=1)
        ax.scatter(g["relative_coverage_new"], y, s=40, color=CLO, zorder=4,
                   label="2026 relative coverage", edgecolor=SURFACE, linewidth=1)
        ax.set_xscale("log")
        ticks = [0.1, 0.2, 0.5, 1, 2, 5, 10, 20]
        ax.set_xticks(ticks, [f"{t:g}" for t in ticks])
        ax.set_xlim(0.1, 25)
        ax.minorticks_off()
        ax.set_yticks(y, [n.replace(", rho 0: one-year default rate SD above history", " *") for n in names],
                      fontsize=8)
        ax.set_title(r)
        ax.grid(axis="y", visible=False)
    axes[0].legend(loc="lower left", fontsize=8, bbox_to_anchor=(0, -0.2))
    fig.suptitle("BBB and BB results under every PLAN sensitivity (grey band = parity, 0.67-1.5)",
                 x=0.01, ha="left", fontsize=12, fontweight="bold")
    fig.text(0.01, 0.005, "* t copula with nu below 9.8 cannot match the historical default-rate volatility "
             "even at zero correlation; run at rho 0 and flagged.", fontsize=8, color=INK2)
    fig.tight_layout(rect=(0, 0.04, 1, 0.94))
    fig.savefig(FIGURES / "04_sensitivity.png", dpi=160)
    plt.close(fig)


def main() -> None:
    FIGURES.mkdir(parents=True, exist_ok=True)
    fig_hero()
    fig_cliff()
    fig_capital()
    fig_recession()
    fig_sensitivity()


if __name__ == "__main__":
    main()

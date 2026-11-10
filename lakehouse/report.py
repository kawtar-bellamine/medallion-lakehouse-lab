"""Figures from the Gold export and the run summary."""
from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import pandas as pd  # noqa: E402

SURFACE, INK, INK2, GRID = "#fcfcfb", "#0b0b0b", "#52514e", "#e4e3df"
COLORS = {"web_ch": "#2a78d6", "web_eu": "#8fb8ea", "store_geneve": "#eb6834", "store_lausanne": "#eda100",
          "store_zurich": "#1baf7a"}
plt.rcParams.update({"figure.facecolor": SURFACE, "axes.facecolor": SURFACE, "savefig.facecolor": SURFACE,
                     "axes.edgecolor": GRID, "axes.labelcolor": INK2, "xtick.color": INK2, "ytick.color": INK2,
                     "font.size": 10, "axes.titlesize": 11, "axes.titleweight": "bold", "axes.spines.top": False,
                     "axes.spines.right": False, "axes.grid": True, "grid.color": GRID, "axes.axisbelow": True,
                     "legend.frameon": False})


def build(root: Path, export: Path, summary: dict):
    fig_dir = root / "docs" / "figures"
    fig_dir.mkdir(parents=True, exist_ok=True)
    kpi = pd.read_csv(export / "kpi_daily_channel.csv")
    kpi["date"] = pd.to_datetime(kpi["date_key"].astype(str))
    pivot = kpi.pivot_table(index="date", columns="channel", values="revenue_chf", aggfunc="sum").fillna(0)

    fig, axes = plt.subplots(1, 2, figsize=(11, 3.6), gridspec_kw={"width_ratios": [2.2, 1]})
    bottom = None
    for ch in COLORS:
        if ch in pivot:
            axes[0].bar(pivot.index, pivot[ch] / 1000, bottom=bottom, color=COLORS[ch], label=ch, width=0.8)
            bottom = pivot[ch] / 1000 if bottom is None else bottom + pivot[ch] / 1000
    axes[0].set_title("Gold: daily revenue by channel (kCHF)"); axes[0].legend(fontsize=8, ncol=3, loc="upper left")
    axes[0].set_ylim(0, (bottom.max() * 1.25)); axes[0].grid(axis="x", visible=False)
    axes[0].tick_params(axis="x", labelsize=8, rotation=30)
    funnel = pd.read_csv(export / "kpi_web_funnel.csv")
    steps = ["page_view", "product_view", "add_to_cart", "checkout", "web_orders"]
    vals = [funnel[s].sum() for s in steps]
    axes[1].barh(range(len(steps))[::-1], vals, color="#2a78d6")
    for i, v in enumerate(vals):
        axes[1].text(v, len(steps) - 1 - i, f"  {v:,.0f}", va="center", fontsize=8, color=INK2)
    axes[1].set_yticks(range(len(steps))[::-1], steps); axes[1].set_xlim(0, max(vals) * 1.35)
    axes[1].set_title("Gold: web funnel (sessions)"); axes[1].grid(axis="y", visible=False)
    fig.tight_layout(); fig.savefig(fig_dir / "gold_kpis.png", dpi=160); plt.close(fig)

    q = summary["quality"]
    labels = ["duplicate lines", "missing customer", "zero quantity", "price in centimes", "unknown product",
              "Swiss date format", "late arrival"]
    inj = [q["duplicates"]["injected"], q["missing_customer"]["injected"], q["zero_quantity"]["injected"],
           q["price_in_cents"]["injected"], q["unknown_product"]["injected"], q["swiss_date_format"]["injected"],
           q["late_arrival"]["injected"]]
    got = [q["duplicates"]["removed"], q["missing_customer"]["caught"], q["zero_quantity"]["caught"],
           q["price_in_cents"]["caught"], q["unknown_product"]["caught"], q["swiss_date_format"]["parsed"],
           q["late_arrival"]["merged_into_order_day"]]
    fig, ax = plt.subplots(figsize=(8.4, 3.8))
    y = range(len(labels))[::-1]
    ax.barh([i + 0.18 for i in y], inj, height=0.36, color="#c9c7c1", label="injected in the sources")
    ax.barh([i - 0.18 for i in y], got, height=0.36, color="#1baf7a", label="handled by Silver")
    for i, (a, b) in zip(y, zip(inj, got)):
        ax.text(max(a, b), i, f"  {b}/{a}", va="center", fontsize=8, color=INK2)
    ax.set_xscale("symlog", linthresh=10); ax.set_yticks(list(y), labels); ax.grid(axis="y", visible=False)
    ax.set_xlim(0, 6000); ax.set_title("Silver: injected defects found and handled (late line with no customer: quarantined)"); ax.legend(fontsize=8, loc="upper center", bbox_to_anchor=(0.5, -0.12), ncol=2)
    fig.tight_layout(); fig.savefig(fig_dir / "quality.png", dpi=160); plt.close(fig)

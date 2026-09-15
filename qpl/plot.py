"""Four facets with shared log timing scale and every scan annotated."""
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd

from .config import RESULTS
from .indexes import CONFIGS
from .queries import QUERIES

def draw(runs, path):
    fig, axes = plt.subplots(2, 2, figsize=(18, 12), sharey=True)
    medians = runs.groupby(["query", "config"])["execution_ms"].median()
    lo, hi = medians.min(), medians.max()
    for ax, query in zip(axes.flat, QUERIES):
        values = [medians.loc[(query.name, c)] for c in CONFIGS]
        bars = ax.bar(range(8), values, color=["#64748b"] + ["#0891b2"]*6 + ["#7c3aed"])
        for bar, config in zip(bars, CONFIGS):
            rows = runs[(runs["query"] == query.name) & (runs["config"] == config)]
            label = "/".join(sorted(rows["events_scan_node"].unique()))
            ax.annotate(label, (bar.get_x()+bar.get_width()/2, bar.get_height()),
                        xytext=(0, 5), textcoords="offset points", rotation=90,
                        ha="center", va="bottom", fontsize=8)
        ax.set_yscale("log")
        ax.set_ylim(max(lo/2, .001), hi*50)
        ax.set_xticks(range(8), [c.replace("_", "\n", 1) for c in CONFIGS], rotation=25, ha="right", fontsize=8)
        ax.set_title(query.name, loc="left", fontweight="bold")
        ax.set_ylabel("Median execution time (ms, log scale)")
        ax.grid(axis="y", alpha=.2)
        ax.set_axisbelow(True)
    fig.suptitle("Query Plan Lab · PostgreSQL 16 · 10 million events", fontsize=18)
    fig.tight_layout()
    fig.savefig(path, dpi=150)
    return fig

def main():
    fig = draw(pd.read_csv(RESULTS / "runs.csv"), RESULTS / "chart.png")
    plt.close(fig)

if __name__ == "__main__":
    main()

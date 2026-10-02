"""Generate the report charts as PNG files in analysis/output/."""

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

from load import CONFIGS, LABELS, OUTPUT_DIR, load_requests, select, throughput_per_run

plt.style.use("grayscale")
CONFIG_NAMES = [f"{LABELS[lb]}\n{LABELS[cluster]}" for lb, cluster in CONFIGS]


def save(fig, name):
    OUTPUT_DIR.mkdir(exist_ok=True)
    fig.tight_layout()
    fig.savefig(OUTPUT_DIR / name, dpi=150)
    plt.close(fig)
    print("Saved", OUTPUT_DIR / name)


def successful_latencies(df):
    return [select(df, lb, cluster).query("success")["latency_ms"] for lb, cluster in CONFIGS]


def latency_boxplot(df):
    fig, ax = plt.subplots(figsize=(8, 5))
    ax.boxplot(successful_latencies(df), flierprops={"markersize": 2})
    ax.set_xticks(range(1, len(CONFIGS) + 1), CONFIG_NAMES)
    ax.set_ylabel("Latency (ms)")
    ax.set_title("Request latency distribution (all runs)")
    save(fig, "latency_boxplot.png")


def latency_bars(df):
    data = successful_latencies(df)
    stats = {
        "Mean": [lat.mean() for lat in data],
        "Median": [lat.median() for lat in data],
        "p95": [lat.quantile(0.95) for lat in data],
    }
    x = np.arange(len(CONFIGS))
    width = 0.25
    fig, ax = plt.subplots(figsize=(8, 5))
    for i, (name, values) in enumerate(stats.items()):
        ax.bar(x + (i - 1) * width, values, width, label=name, color=str(0.2 + 0.3 * i), edgecolor="black")
    ax.set_xticks(x, CONFIG_NAMES)
    ax.set_ylabel("Latency (ms)")
    ax.set_title("Mean, median and p95 latency")
    ax.legend()
    save(fig, "latency_bars.png")


def throughput_bars(df):
    throughput = throughput_per_run(df)
    values = [select(throughput, lb, cluster)["throughput"] for lb, cluster in CONFIGS]
    fig, ax = plt.subplots(figsize=(8, 5))
    ax.bar(CONFIG_NAMES, [v.mean() for v in values], yerr=[v.std() for v in values],
           capsize=5, color="0.6", edgecolor="black")
    ax.set_ylabel("Throughput (successful req/s)")
    ax.set_title("Throughput (mean ± SD across runs)")
    save(fig, "throughput_bars.png")


def request_share(df):
    fig, axes = plt.subplots(2, 2, figsize=(10, 7), sharey=True)
    for ax, (lb, cluster) in zip(axes.flat, CONFIGS):
        instances = sorted(df.loc[(df["cluster"] == cluster) & df["success"], "backend_instance"].unique())
        requests = select(df, lb, cluster).query("success")
        shares = requests["backend_instance"].value_counts(normalize=True).reindex(instances, fill_value=0)
        ax.bar([instance[-6:] for instance in instances], shares * 100, color="0.6", edgecolor="black")
        ax.set_title(f"{LABELS[lb]} – {LABELS[cluster]}")
        ax.set_ylabel("Share of requests (%)")
    fig.suptitle("Share of requests per instance (all runs)")
    save(fig, "request_share.png")


if __name__ == "__main__":
    df = load_requests()
    latency_boxplot(df)
    latency_bars(df)
    throughput_bars(df)
    request_share(df)

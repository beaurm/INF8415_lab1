"""Generate the report tables as a plain black-and-white HTML page (analysis/output/tables.html).

Open the page in a browser, select a table and paste it into Google Docs.
"""

import numpy as np
import pandas as pd
from scipy.stats import mannwhitneyu

from load import CONFIGS, LABELS, OUTPUT_DIR, load_requests, select, throughput_per_run

STYLE = """
body { font-family: Arial, sans-serif; color: #000; background: #fff; margin: 2em; }
h2 { font-size: 14pt; margin-top: 2em; }
table { border-collapse: collapse; }
th, td { border: 1px solid #000; padding: 4px 8px; text-align: right; }
th { text-align: center; }
p { font-size: 10pt; max-width: 50em; }
"""


def html_table(title, rows, note=""):
    return f"<h2>{title}</h2>\n{pd.DataFrame(rows).to_html(index=False, border=0)}\n<p>{note}</p>\n"


def latencies(df, load_balancer, cluster):
    requests = select(df, load_balancer, cluster)
    return requests.loc[requests["success"], "latency_ms"]


def throughputs(throughput, load_balancer, cluster):
    return select(throughput, load_balancer, cluster)["throughput"]


def descriptive_table(df, throughput):
    rows = []
    for lb, cluster in CONFIGS:
        requests = select(df, lb, cluster)
        lat = latencies(df, lb, cluster)
        tp = throughputs(throughput, lb, cluster)
        rows.append({
            "LB": LABELS[lb],
            "Cluster": LABELS[cluster],
            "N": len(requests),
            "Success": f"{requests['success'].mean():.1%}",
            "Mean (ms)": f"{lat.mean():.1f}",
            "Median (ms)": f"{lat.median():.1f}",
            "SD (ms)": f"{lat.std():.1f}",
            "IQR (ms)": f"{lat.quantile(0.75) - lat.quantile(0.25):.1f}",
            "Min (ms)": f"{lat.min():.1f}",
            "Max (ms)": f"{lat.max():.1f}",
            "p95 (ms)": f"{lat.quantile(0.95):.1f}",
            "p99 (ms)": f"{lat.quantile(0.99):.1f}",
            "Throughput (req/s)": f"{tp.mean():.0f} ± {tp.std():.0f}",
        })
    return html_table(
        "Table 1. Descriptive statistics per configuration",
        rows,
        "Latency statistics pool the successful requests of all runs. Throughput is the mean ± SD across runs.",
    )


def repeatability_table(df, throughput):
    rows = []
    for lb, cluster in CONFIGS:
        requests = select(df, lb, cluster)
        per_run = requests[requests["success"]].groupby("run_id")["latency_ms"]
        means, p95s = per_run.mean(), per_run.quantile(0.95)
        tp = throughputs(throughput, lb, cluster)
        rows.append({
            "LB": LABELS[lb],
            "Cluster": LABELS[cluster],
            "Runs": requests["run_id"].nunique(),
            "Mean latency (ms)": f"{means.mean():.1f} ± {means.std():.1f}",
            "p95 latency (ms)": f"{p95s.mean():.1f} ± {p95s.std():.1f}",
            "Throughput (req/s)": f"{tp.mean():.0f} ± {tp.std():.0f}",
        })
    return html_table(
        "Table 2. Repeatability across runs",
        rows,
        "Each metric is computed once per run, then reported as mean ± SD across runs.",
    )


def cluster_table(df, throughput):
    rows = []
    for lb in ("alb", "custom"):
        c1, c2 = latencies(df, lb, "cluster1"), latencies(df, lb, "cluster2")
        t1, t2 = throughputs(throughput, lb, "cluster1").mean(), throughputs(throughput, lb, "cluster2").mean()
        for name, v1, v2 in (("Mean", c1.mean(), c2.mean()), ("p95", c1.quantile(0.95), c2.quantile(0.95))):
            rows.append({
                "LB": LABELS[lb],
                "Metric": f"{name} latency (ms)",
                "C1": f"{v1:.1f}",
                "C2": f"{v2:.1f}",
                "Change": f"{(v1 - v2) / v1:+.1%} improvement",
            })
        rows.append({
            "LB": LABELS[lb],
            "Metric": "Throughput (req/s)",
            "C1": f"{t1:.0f}",
            "C2": f"{t2:.0f}",
            "Change": f"{(t2 - t1) / t1:+.1%} gain",
        })
    return html_table(
        "Table 3. Small (C1) vs large (C2) cluster",
        rows,
        "Latency improvement = (C1 − C2) / C1. Throughput gain = (C2 − C1) / C1.",
    )


def lb_table(df, throughput):
    rows = []
    for cluster in ("cluster1", "cluster2"):
        alb, custom = latencies(df, "alb", cluster), latencies(df, "custom", cluster)
        metrics = [
            ("Mean latency (ms)", alb.mean(), custom.mean()),
            ("Median latency (ms)", alb.median(), custom.median()),
            ("p95 latency (ms)", alb.quantile(0.95), custom.quantile(0.95)),
            ("p99 latency (ms)", alb.quantile(0.99), custom.quantile(0.99)),
            ("Throughput (req/s)", throughputs(throughput, "alb", cluster).mean(),
             throughputs(throughput, "custom", cluster).mean()),
        ]
        for name, a, c in metrics:
            rows.append({
                "Cluster": LABELS[cluster],
                "Metric": name,
                "ALB": f"{a:.1f}",
                "Custom LB": f"{c:.1f}",
                "Difference": f"{(c - a) / a:+.1%}",
            })
        errors = [1 - select(df, lb, cluster)["success"].mean() for lb in ("alb", "custom")]
        rows.append({
            "Cluster": LABELS[cluster],
            "Metric": "Error rate",
            "ALB": f"{errors[0]:.1%}",
            "Custom LB": f"{errors[1]:.1%}",
            "Difference": f"{(errors[1] - errors[0]) * 100:+.1f} pp",
        })
    return html_table(
        "Table 4. AWS ALB vs custom load balancer",
        rows,
        "Difference = (Custom − ALB) / ALB. A negative latency difference means the custom LB is faster.",
    )


def distribution_tables(df):
    share_rows, fairness_rows = [], []
    for lb, cluster in CONFIGS:
        # Every instance of the cluster counts, including those that received no request
        instances = sorted(df.loc[(df["cluster"] == cluster) & df["success"], "backend_instance"].unique())
        requests = select(df, lb, cluster)
        requests = requests[requests["success"]]
        counts = requests["backend_instance"].value_counts().reindex(instances, fill_value=0)
        shares = counts / counts.sum()

        for instance in instances:
            lat = requests.loc[requests["backend_instance"] == instance, "latency_ms"]
            share_rows.append({
                "LB": LABELS[lb],
                "Cluster": LABELS[cluster],
                "Instance": instance,
                "Requests": counts[instance],
                "Share": f"{shares[instance]:.1%}",
                "Mean latency (ms)": f"{lat.mean():.1f}" if len(lat) else "–",
                "p95 latency (ms)": f"{lat.quantile(0.95):.1f}" if len(lat) else "–",
            })

        nonzero = shares[shares > 0]
        entropy = -(nonzero * np.log(nonzero)).sum() / np.log(len(instances))
        fairness_rows.append({
            "LB": LABELS[lb],
            "Cluster": LABELS[cluster],
            "Instances": len(instances),
            "Instances used": len(nonzero),
            "CV of request counts": f"{counts.std(ddof=0) / counts.mean():.2f}",
            "Normalized entropy": f"{entropy:.2f}",
        })

    return html_table(
        "Table 5. Request distribution per instance",
        share_rows,
        "All runs pooled, successful requests only.",
    ) + html_table(
        "Table 6. Load distribution fairness",
        fairness_rows,
        "CV = SD / mean of the request counts per instance (0 = perfectly even). "
        "Normalized entropy = H / ln(N): 1 = perfectly even, 0 = all traffic on one instance.",
    )


def cliffs_delta_magnitude(delta):
    size = abs(delta)
    return "negligible" if size < 0.147 else "small" if size < 0.33 else "medium" if size < 0.474 else "large"


def tests_table(df):
    comparisons = [
        (f"ALB vs Custom LB, {LABELS['cluster1']}", ("alb", "cluster1"), ("custom", "cluster1")),
        (f"ALB vs Custom LB, {LABELS['cluster2']}", ("alb", "cluster2"), ("custom", "cluster2")),
        ("C1 vs C2, ALB", ("alb", "cluster1"), ("alb", "cluster2")),
        ("C1 vs C2, Custom LB", ("custom", "cluster1"), ("custom", "cluster2")),
    ]
    rows = []
    for name, first, second in comparisons:
        a, b = latencies(df, *first), latencies(df, *second)
        u, p = mannwhitneyu(a, b)
        delta = 2 * u / (len(a) * len(b)) - 1  # P(a > b) - P(a < b)
        rows.append({
            "Comparison (A vs B)": name,
            "Median A (ms)": f"{a.median():.1f}",
            "Median B (ms)": f"{b.median():.1f}",
            "Mann–Whitney U": f"{u:.0f}",
            "p-value": f"{p:.2e}",
            "Cliff's δ": f"{delta:+.2f}",
            "Effect size": cliffs_delta_magnitude(delta),
        })
    return html_table(
        "Table 7. Statistical tests on request latency",
        rows,
        "Two-sided Mann–Whitney U test on the pooled request latencies. Cliff's δ = P(A > B) − P(A < B): "
        "positive means A is slower. Requests of the same run are not fully independent, so p-values are optimistic; "
        "the effect size is the more meaningful number.",
    )


if __name__ == "__main__":
    df = load_requests()
    throughput = throughput_per_run(df)
    sections = [
        descriptive_table(df, throughput),
        repeatability_table(df, throughput),
        cluster_table(df, throughput),
        lb_table(df, throughput),
        distribution_tables(df),
        tests_table(df),
    ]
    OUTPUT_DIR.mkdir(exist_ok=True)
    page = (f"<!doctype html>\n<html><head><meta charset='utf-8'><title>Benchmark tables</title>"
            f"<style>{STYLE}</style></head><body>\n{''.join(sections)}</body></html>")
    (OUTPUT_DIR / "tables.html").write_text(page)
    print("Saved", OUTPUT_DIR / "tables.html")

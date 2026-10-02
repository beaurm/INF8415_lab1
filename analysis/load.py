"""Load results/requests.csv (one row per benchmark request) for the analysis scripts."""

from pathlib import Path

import pandas as pd

CSV_PATH = Path(__file__).resolve().parents[1] / "results" / "requests.csv"
OUTPUT_DIR = Path(__file__).resolve().parent / "output"

# Order used in every table and chart
CONFIGS = [("alb", "cluster1"), ("alb", "cluster2"), ("custom", "cluster1"), ("custom", "cluster2")]
LABELS = {"alb": "ALB", "custom": "Custom LB", "cluster1": "C1 (t3.micro)", "cluster2": "C2 (m7g.large)"}


def load_requests():
    df = pd.read_csv(CSV_PATH)
    df["success"] = df["status_code"] == 200
    df["end"] = df["timestamp"] + df["latency_ms"] / 1000
    return df


def select(df, load_balancer, cluster):
    return df[(df["load_balancer"] == load_balancer) & (df["cluster"] == cluster)]


def throughput_per_run(df):
    # Successful requests divided by the time between the first request sent and the last answer received
    runs = df.groupby(["load_balancer", "cluster", "run_id"])
    duration = runs["end"].max() - runs["timestamp"].min()
    return (runs["success"].sum() / duration).rename("throughput").reset_index()

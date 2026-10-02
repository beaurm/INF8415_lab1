"""Benchmark: send 1000 concurrent requests to each cluster, through the ALB and the custom LB.

Every request is appended as one row to results/requests.csv; analysis is done separately from that file.
"""

import asyncio
import csv
import sys
import time
from pathlib import Path

import aiohttp

NUM_REQUESTS = 1000
CSV_PATH = Path(__file__).resolve().parents[1] / "results" / "requests.csv"
FIELDS = ["run_id", "timestamp", "load_balancer", "cluster", "request_id",
          "backend_instance", "status_code", "latency_ms", "team_seed", "error"]


async def single_request(session, url, request_id):
    row = {"request_id": request_id, "timestamp": time.time()}
    start = time.perf_counter()
    try:
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=30)) as resp:
            body = await resp.json()
            row.update(status_code=resp.status, backend_instance=body.get("instance_id"),
                       team_seed=resp.headers.get("X-Team-Seed"))
    except Exception as error:
        row["error"] = str(error)
    row["latency_ms"] = (time.perf_counter() - start) * 1000
    return row


async def benchmark_cluster(base_url, cluster):
    async with aiohttp.ClientSession() as session:
        tasks = [single_request(session, f"http://{base_url}/{cluster}", i) for i in range(NUM_REQUESTS)]
        return await asyncio.gather(*tasks)


def benchmark_all(alb_url, custom_lb_url, runs=1):
    new_file = not CSV_PATH.exists()
    CSV_PATH.parent.mkdir(exist_ok=True)
    with CSV_PATH.open("a", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDS)
        if new_file:
            writer.writeheader()

        for _ in range(runs):
            run_id = time.strftime("%Y%m%d-%H%M%S")
            for load_balancer, base_url in (("alb", alb_url), ("custom", custom_lb_url)):
                for cluster in ("cluster1", "cluster2"):
                    rows = asyncio.run(benchmark_cluster(base_url, cluster))
                    for row in rows:
                        row.update(run_id=run_id, load_balancer=load_balancer, cluster=cluster)
                    writer.writerows(rows)

    print(f"Saved {runs} run(s) to {CSV_PATH}")


if __name__ == "__main__":
    # Usage: benchmark.py <alb-dns> <custom-lb-ip:port> [runs]
    benchmark_all(sys.argv[1], sys.argv[2], int(sys.argv[3]) if len(sys.argv) > 3 else 1)

"""Benchmark: send 1000 concurrent requests to /cluster1 and /cluster2."""

import asyncio
import statistics
import sys
import time
from urllib.parse import urljoin

import aiohttp

NUM_REQUESTS = 1000


async def single_request(session, url, request_id):
    start = time.perf_counter()
    try:
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=30)) as resp:
            body = await resp.json()
            latency = time.perf_counter() - start
            return {
                "id": request_id,
                "status": resp.status,
                "latency": latency,
                "instance_id": body.get("instance_id"),
                "cluster": body.get("cluster"),
                "team_seed": body.get("team_seed"),
                "seed_header": resp.headers.get("X-Team-Seed"),
            }
    except Exception as exc:
        return {"id": request_id, "error": str(exc), "latency": time.perf_counter() - start}


async def benchmark_endpoint(base_url, path, label):
    url = urljoin(base_url, path)
    print(f"\n=== Benchmarking {label} ({url}) ===")

    async with aiohttp.ClientSession() as session:
        start = time.perf_counter()
        tasks = [single_request(session, url, i) for i in range(NUM_REQUESTS)]
        results = await asyncio.gather(*tasks)
        total = time.perf_counter() - start

    errors = [r for r in results if "error" in r]
    ok = [r for r in results if "error" not in r]
    latencies = [r["latency"] for r in ok]

    instance_counts = {}
    for r in ok:
        instance_counts[r["instance_id"]] = instance_counts.get(r["instance_id"], 0) + 1

    print(f"Total wall time:       {total:.2f} s")
    if latencies:
        print(f"Successful requests:   {len(ok)}/{NUM_REQUESTS}")
        print(f"Avg latency:           {statistics.mean(latencies)*1000:.2f} ms")
        print(f"Median latency:        {statistics.median(latencies)*1000:.2f} ms")
        print(f"Min / Max latency:     {min(latencies)*1000:.2f} / {max(latencies)*1000:.2f} ms")
    if errors:
        print(f"Errors:                {len(errors)}")
    print(f"Requests per instance: {instance_counts}")
    print(f"Team seed seen:        {set(r.get('team_seed') for r in ok)}")

    return {"label": label, "total": total, "ok": len(ok), "errors": len(errors),
            "latencies": latencies, "instance_counts": instance_counts}


async def main():
    base_url = sys.argv[1] if len(sys.argv) > 1 else input("ALB DNS (http://...): ").strip()
    if not base_url.startswith("http"):
        base_url = "http://" + base_url

    r1 = await benchmark_endpoint(base_url, "/cluster1", "cluster1 (small)")
    r2 = await benchmark_endpoint(base_url, "/cluster2", "cluster2 (large)")

    print("\n=== Summary ===")
    if r1['latencies']:
        print(f"Cluster1: {r1['total']:.2f}s total, {r1['ok']}/{NUM_REQUESTS} OK, "
              f"avg {statistics.mean(r1['latencies'])*1000:.2f} ms")
    if r2['latencies']:
        print(f"Cluster2: {r2['total']:.2f}s total, {r2['ok']}/{NUM_REQUESTS} OK, "
              f"avg {statistics.mean(r2['latencies'])*1000:.2f} ms")


if __name__ == "__main__":
    asyncio.run(main())
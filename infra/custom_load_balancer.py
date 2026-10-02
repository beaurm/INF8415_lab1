"""Route each cluster to the instance with the fastest /health response."""

import asyncio
from contextlib import asynccontextmanager
import time

import boto3
from fastapi import FastAPI, HTTPException
from fastapi.responses import Response
import httpx
import uvicorn

from config import APP_PORT, AWS_REGION, CLUSTER1, CLUSTER2, PROJECT_TAG, TEAM_SEED

CLUSTERS = (CLUSTER1["name"], CLUSTER2["name"])
ec2 = boto3.client("ec2", region_name=AWS_REGION)
fastest = {}
client = httpx.AsyncClient(timeout=5.0)


FAILOVER_THRESHOLD_MS = 50 + (TEAM_SEED % 200)


def get_project_instances():
    instances = []
    pages = ec2.get_paginator("describe_instances").paginate(Filters=[
        {"Name": "tag:Project", "Values": [PROJECT_TAG]},
        {"Name": "instance-state-name", "Values": ["running"]},
    ])
    for page in pages:
        for reservation in page["Reservations"]:
            for instance in reservation["Instances"]:
                tags = {tag["Key"]: tag["Value"] for tag in instance.get("Tags", [])}
                cluster = tags.get("Cluster")
                if cluster in CLUSTERS and instance.get("PrivateIpAddress"):
                    instances.append((cluster, instance["InstanceId"], instance["PrivateIpAddress"]))
    return instances


async def get_health(instance):
    cluster, instance_id, ip = instance
    start = time.perf_counter()
    response = await client.get(f"http://{ip}:{APP_PORT}/health")
    response.raise_for_status()
    return cluster, instance_id, ip, time.perf_counter() - start


async def refresh_targets():
    instances = await asyncio.to_thread(get_project_instances)
    results = await asyncio.gather(*(get_health(instance) for instance in instances), return_exceptions=True)
    
    healthy = [result for result in results if isinstance(result, tuple)]

    for cluster in CLUSTERS:
        candidates = [result for result in healthy if result[0] == cluster]
        if not candidates:
            fastest.pop(cluster, None)
            continue

        current = fastest.get(cluster)

        if current is not None:
            still_healthy = [c for c in candidates if c[1] == current[1]]
            if still_healthy and (still_healthy[0][3] * 1000) <= FAILOVER_THRESHOLD_MS:
                fastest[cluster] = still_healthy[0]
                continue

        # Sinon, on bascule vers l'instance la plus rapide disponible.
        fastest[cluster] = min(candidates, key=lambda result: result[3])


async def monitor():
    while True:
        await refresh_targets()
        await asyncio.sleep(3)


@asynccontextmanager
async def lifespan(app):
    await refresh_targets()
    task = asyncio.create_task(monitor())
    try:
        yield
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        await client.aclose()


app = FastAPI(lifespan=lifespan)


async def send_to_fastest(cluster):
    if cluster not in fastest:
        raise HTTPException(status_code=503, detail="No healthy instances")
    _, _, ip, _ = fastest[cluster]
    return await client.get(f"http://{ip}:{APP_PORT}/{cluster}")


async def forward_request(cluster):
    try:
        response = await send_to_fastest(cluster)
    except httpx.HTTPError:
        # The instance died since the last check: check again now and retry once.
        await refresh_targets()
        response = await send_to_fastest(cluster)
    return Response(content=response.content, status_code=response.status_code,
                    headers={"content-type": response.headers["content-type"],
                             "x-team-seed": response.headers["x-team-seed"]})


@app.get("/cluster1")
async def cluster1():
    return await forward_request("cluster1")


@app.get("/cluster2")
async def cluster2():
    return await forward_request("cluster2")


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8080)
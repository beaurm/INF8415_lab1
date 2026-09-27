import hashlib
import logging
import os

from fastapi import FastAPI, HTTPException, Request

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

STUDENT_IDS = sorted(["2278089", "2291231", "2251271", "2256783"])
TEAM_SEED = int(hashlib.sha256("-".join(STUDENT_IDS).encode()).hexdigest(), 16) % 10000
INSTANCE_ID = os.getenv("INSTANCE_ID", "local-dev")
CLUSTER_NAME = os.getenv("CLUSTER_NAME", "cluster1").lower()

# Create FastAPI app
app = FastAPI()

@app.middleware("http")
async def add_team_seed_header(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Team-Seed"] = str(TEAM_SEED)
    return response

def instance_response(required_cluster: str | None = None):
    if required_cluster and CLUSTER_NAME != required_cluster:
        raise HTTPException(status_code=404, detail="Route not available on this cluster")

    message = f"Instance {INSTANCE_ID} in {CLUSTER_NAME} is responding."
    logger.info(message)
    return {
        "message": message,
        "instance_id": INSTANCE_ID,
        "cluster": CLUSTER_NAME,
        "team_seed": TEAM_SEED,
    }

@app.get("/")
async def root():
    return instance_response()

@app.get("/health")
async def health():
    return {
        "status": "ok",
        "instance_id": INSTANCE_ID,
        "cluster": CLUSTER_NAME,
        "team_seed": TEAM_SEED,
    }

@app.get("/cluster1")
async def cluster1():
    return instance_response("cluster1")

@app.get("/cluster2")
async def cluster2():
    return instance_response("cluster2")


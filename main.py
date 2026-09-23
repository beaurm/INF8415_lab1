from fastapi import FastAPI
import uvicorn
import logging

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Create FastAPI app
app = FastAPI()


@app.get("/")
async def root():
    message = "Instance has received the request"
    logger.info(message)
    return {"message": message}


if __name__ == "__main__":
    # uvicorn.run(app, host="0.0.0.0", port=8000)
    import hashlib
    student_ids = sorted(["2278089", "2291231", "2251271", "2256783"])
    joined = "-".join(student_ids)
    seed = int(hashlib.sha256(joined.encode()).hexdigest(), 16) % 10000
    print(seed)


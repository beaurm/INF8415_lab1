"""Deploy the FastAPI app to the existing EC2 clusters over SSH."""

import json
import re
import shutil
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from urllib.error import URLError
from urllib.request import urlopen

import boto3
from botocore.exceptions import BotoCoreError, ClientError

from config import (
    APP_PORT,
    AWS_REGION,
    CLUSTER1,
    CLUSTER2,
    KEY_NAME,
    LOADBALANCER,
    PROJECT_TAG,
    TEAM_SEED,
)

ec2 = boto3.client("ec2", region_name=AWS_REGION)
PROJECT_ROOT = Path(__file__).resolve().parents[1]
INFRA_DIR = Path(__file__).resolve().parent
APP_PATH = PROJECT_ROOT / "main.py"
LB_APP_PATH = INFRA_DIR / "custom_load_balancer.py"
CONFIG_PATH = INFRA_DIR / "config.py"
KEY_PATH = PROJECT_ROOT / f"{KEY_NAME}.pem"
REMOTE_DIR = "/home/ec2-user/assignment1"
SERVICE_NAME = "assignment1-api"
LB_SERVICE_NAME = "assignment1-lb"
EXPECTED_COUNTS = {
    CLUSTER1["name"]: CLUSTER1["count"],
    CLUSTER2["name"]: CLUSTER2["count"],
    LOADBALANCER["name"]: LOADBALANCER["count"],
}


def validate_local_prerequisites():
    missing = [tool for tool in ("ssh", "scp") if shutil.which(tool) is None]
    if missing:
        raise RuntimeError("Missing local OpenSSH tools: " + ", ".join(missing))
    if not APP_PATH.is_file():
        raise RuntimeError(f"Application file not found: {APP_PATH}")
    if not LB_APP_PATH.is_file():
        raise RuntimeError(f"Load Balancer file not found: {LB_APP_PATH}")
    if not CONFIG_PATH.is_file():
        raise RuntimeError(f"Config file not found: {CONFIG_PATH}")
    if not KEY_PATH.is_file():
        raise RuntimeError(f"SSH key not found: {KEY_PATH}")


def get_project_instances():
    paginator = ec2.get_paginator("describe_instances")
    pages = paginator.paginate(
        Filters=[
            {"Name": "tag:Project", "Values": [PROJECT_TAG]},
            {"Name": "instance-state-name", "Values": ["running"]},
        ]
    )

    instances = []
    for page in pages:
        for reservation in page["Reservations"]:
            for instance in reservation["Instances"]:
                tags = {tag["Key"]: tag["Value"] for tag in instance.get("Tags", [])}
                cluster = tags.get("Cluster")
                instance_id = instance["InstanceId"]
                public_ip = instance.get("PublicIpAddress")

                if cluster not in EXPECTED_COUNTS:
                    raise RuntimeError(f"Instance {instance_id} has an unexpected cluster tag: {cluster}")
                if not re.fullmatch(r"i-[0-9a-f]+", instance_id):
                    raise RuntimeError(f"Unexpected EC2 instance ID: {instance_id}")
                if not public_ip:
                    raise RuntimeError(f"Instance {instance_id} has no public IPv4 address for SSH deployment")

                instances.append(
                    {"instance_id": instance_id, "cluster": cluster, "public_ip": public_ip}
                )

    counts = {name: sum(item["cluster"] == name for item in instances) for name in EXPECTED_COUNTS}
    if counts != EXPECTED_COUNTS:
        raise RuntimeError(
            f"Expected running instance counts {EXPECTED_COUNTS}, found {counts}. "
            "Start or repair the EC2 clusters before deploying."
        )

    return sorted(instances, key=lambda item: (item["cluster"], item["instance_id"]))


def run_process(command, *, label, input_text=None):
    input_bytes = input_text.replace("\r\n", "\n").encode("utf-8") if input_text is not None else None
    result = subprocess.run(
        command,
        input=input_bytes,
        capture_output=True,
        check=False,
    )
    if result.returncode:
        detail = (
            result.stderr.decode("utf-8", errors="replace").strip()
            or result.stdout.decode("utf-8", errors="replace").strip()
            or "no command output"
        )
        raise RuntimeError(f"{label} failed (exit {result.returncode}): {detail}")
    return result.stdout.decode("utf-8", errors="replace").strip()


def ssh_command(instance, script):
    return run_process(
        [
            "ssh",
            "-i",
            str(KEY_PATH),
            "-o",
            "BatchMode=yes",
            "-o",
            "StrictHostKeyChecking=accept-new",
            "-o",
            "ConnectTimeout=10",
            f"ec2-user@{instance['public_ip']}",
            "bash -s",
        ],
        label=f"SSH to {instance['instance_id']}",
        input_text=script,
    )


def deploy_instance(instance):
    """Deploy main.py (FastAPI app) on an application instance (cluster1 or cluster2)."""
    instance_id = instance["instance_id"]
    cluster = instance["cluster"]
    print(f"[{instance_id}] Preparing {cluster}")

    ssh_command(
        instance,
        f"""set -euo pipefail
sudo dnf install -y python3.12 python3.12-pip
mkdir -p {REMOTE_DIR}
python3.12 -m venv {REMOTE_DIR}/.venv
{REMOTE_DIR}/.venv/bin/python -m pip install --disable-pip-version-check --quiet fastapi==0.141.1 'uvicorn[standard]==0.53.0'
""",
    )

    run_process(
        [
            "scp",
            "-i",
            str(KEY_PATH),
            "-o",
            "BatchMode=yes",
            "-o",
            "StrictHostKeyChecking=accept-new",
            "-o",
            "ConnectTimeout=10",
            str(APP_PATH),
            f"ec2-user@{instance['public_ip']}:{REMOTE_DIR}/main.py",
        ],
        label=f"Copy main.py to {instance_id}",
    )

    service = f"""[Unit]
Description=INF8415 FastAPI application
After=network-online.target
Wants=network-online.target

[Service]
User=ec2-user
WorkingDirectory={REMOTE_DIR}
Environment=INSTANCE_ID={instance_id}
Environment=CLUSTER_NAME={cluster}
ExecStart={REMOTE_DIR}/.venv/bin/uvicorn main:app --host 0.0.0.0 --port {APP_PORT}
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
"""
    remote_setup = f"""set -euo pipefail
sudo tee /etc/systemd/system/{SERVICE_NAME}.service >/dev/null <<'UNIT'
{service}UNIT
sudo systemctl daemon-reload
sudo systemctl enable {SERVICE_NAME}
sudo systemctl restart {SERVICE_NAME}
sudo systemctl is-active --quiet {SERVICE_NAME}
"""
    ssh_command(instance, remote_setup)
    verify_instance(instance)
    print(f"[{instance_id}] Deployment and health check passed")


def deploy_lb_instance(instance):
    """Deploy custom_load_balancer.py on the dedicated LB instance."""
    instance_id = instance["instance_id"]
    print(f"[{instance_id}] Preparing Load Balancer")

    ssh_command(
        instance,
        f"""set -euo pipefail
sudo dnf install -y python3.12 python3.12-pip
mkdir -p {REMOTE_DIR}
python3.12 -m venv {REMOTE_DIR}/.venv
{REMOTE_DIR}/.venv/bin/python -m pip install --disable-pip-version-check --quiet fastapi==0.141.1 'uvicorn[standard]==0.53.0' httpx boto3
""",
    )

    # Copy both custom_load_balancer.py AND config.py (needed for imports)
    for src_path, dest_name in [(LB_APP_PATH, "custom_load_balancer.py"), (CONFIG_PATH, "config.py")]:
        run_process(
            [
                "scp",
                "-i",
                str(KEY_PATH),
                "-o",
                "BatchMode=yes",
                "-o",
                "StrictHostKeyChecking=accept-new",
                "-o",
                "ConnectTimeout=10",
                str(src_path),
                f"ec2-user@{instance['public_ip']}:{REMOTE_DIR}/{dest_name}",
            ],
            label=f"Copy {dest_name} to {instance_id}",
        )

    service = f"""[Unit]
Description=INF8415 Custom Load Balancer
After=network-online.target
Wants=network-online.target

[Service]
User=ec2-user
WorkingDirectory={REMOTE_DIR}
ExecStart={REMOTE_DIR}/.venv/bin/uvicorn custom_load_balancer:app --host 0.0.0.0 --port {APP_PORT}
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
"""
    remote_setup = f"""set -euo pipefail
sudo tee /etc/systemd/system/{LB_SERVICE_NAME}.service >/dev/null <<'UNIT'
{service}UNIT
sudo systemctl daemon-reload
sudo systemctl enable {LB_SERVICE_NAME}
sudo systemctl restart {LB_SERVICE_NAME}
sudo systemctl is-active --quiet {LB_SERVICE_NAME}
"""
    ssh_command(instance, remote_setup)
    print(f"[{instance_id}] Load Balancer deployed on port {APP_PORT}")


def verify_instance(instance):
    instance_id = instance["instance_id"]
    cluster = instance["cluster"]
    url = f"http://{instance['public_ip']}:{APP_PORT}/{cluster}"
    last_error = None

    for _ in range(20):
        try:
            with urlopen(url, timeout=5) as response:
                payload = json.loads(response.read().decode("utf-8"))
                seed_header = response.headers.get("X-Team-Seed")
            if (
                payload.get("instance_id") == instance_id
                and payload.get("cluster") == cluster
                and payload.get("team_seed") == TEAM_SEED
                and seed_header == str(TEAM_SEED)
            ):
                return
            raise RuntimeError(f"Unexpected response from {instance_id}: {payload}")
        except (URLError, TimeoutError) as error:
            last_error = error
            time.sleep(3)

    raise RuntimeError(f"Health check failed for {instance_id} at {url}: {last_error}")


def main():
    try:
        validate_local_prerequisites()
        instances = get_project_instances()
        print(f"Deploying to {len(instances)} running instances in {AWS_REGION}")

        # Separate the LB instance from the application instances
        lb_instances = [i for i in instances if i["cluster"] == LOADBALANCER["name"]]
        app_instances = [i for i in instances if i["cluster"] != LOADBALANCER["name"]]

        failures = []

        # Deploy main.py on the 9 application instances (in parallel)
        with ThreadPoolExecutor(max_workers=len(app_instances)) as executor:
            deployments = {executor.submit(deploy_instance, instance): instance for instance in app_instances}
            for future in as_completed(deployments):
                instance_id = deployments[future]["instance_id"]
                try:
                    future.result()
                except Exception as error:
                    failures.append((instance_id, error))
                    print(f"[{instance_id}] FAILED: {error}")

        # Deploy custom_load_balancer.py on the LB instance
        for instance in lb_instances:
            try:
                deploy_lb_instance(instance)
            except Exception as error:
                failures.append((instance["instance_id"], error))
                print(f"[{instance['instance_id']}] FAILED: {error}")

        if failures:
            failed_ids = ", ".join(instance_id for instance_id, _ in failures)
            raise RuntimeError(f"Deployment failed on {len(failures)} instance(s): {failed_ids}")

        print("Deployment completed successfully on all instances.")
        if lb_instances:
            lb_ip = lb_instances[0]["public_ip"]
            print(f"Load Balancer public IP: {lb_ip}")
            print(f"Test with: curl http://{lb_ip}:{APP_PORT}/cluster1")
    except (BotoCoreError, ClientError) as error:
        raise SystemExit(f"AWS discovery failed: {error}") from error
    except RuntimeError as error:
        raise SystemExit(str(error)) from error


if __name__ == "__main__":
    main()
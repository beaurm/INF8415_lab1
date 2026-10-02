"""Install the FastAPI app on the cluster instances and the custom LB on its own instance, over SSH."""

import subprocess
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import boto3

from config import APP_PORT, AWS_REGION, KEY_PATH, LOADBALANCER, PROJECT_TAG

ec2 = boto3.client("ec2", region_name=AWS_REGION)
INFRA_DIR = Path(__file__).resolve().parent
REMOTE_DIR = "/home/ec2-user"
SSH_OPTIONS = ["-i", str(KEY_PATH), "-o", "StrictHostKeyChecking=no", "-o", "LogLevel=ERROR"]


def get_project_instances():
    response = ec2.describe_instances(
        Filters=[
            {"Name": "tag:Project", "Values": [PROJECT_TAG]},
            {"Name": "instance-state-name", "Values": ["running"]},
        ]
    )
    instances = []
    for reservation in response["Reservations"]:
        for instance in reservation["Instances"]:
            tags = {tag["Key"]: tag["Value"] for tag in instance["Tags"]}
            instances.append(
                {
                    "instance_id": instance["InstanceId"],
                    "cluster": tags["Cluster"],
                    "public_ip": instance["PublicIpAddress"],
                }
            )
    return instances


def deploy_instance(instance):
    if instance["cluster"] == LOADBALANCER["name"]:
        files = [INFRA_DIR / "custom_load_balancer.py", INFRA_DIR / "config.py"]
        packages = "fastapi==0.141.1 'uvicorn[standard]==0.53.0' httpx boto3"
        app = "custom_load_balancer:app"
    else:
        files = [INFRA_DIR.parent / "main.py"]
        packages = "fastapi==0.141.1 'uvicorn[standard]==0.53.0'"
        app = "main:app"

    print(f"[{instance['instance_id']}] Deploying {instance['cluster']}")
    host = f"ec2-user@{instance['public_ip']}"

    # Copies the appropriate file to the remote depending on instance type
    subprocess.run(["scp", *SSH_OPTIONS, *map(str, files), f"{host}:{REMOTE_DIR}/"], check=True)

    # Installs Python and dependencies, then runs the app as a systemd service
    # so it keeps running after the SSH session ends.
    setup = f"""set -e
sudo dnf install -q -y python3.12 python3.12-pip
python3.12 -m venv {REMOTE_DIR}/.venv
{REMOTE_DIR}/.venv/bin/pip install --quiet {packages}
sudo tee /etc/systemd/system/assignment1.service > /dev/null <<'EOF'
[Unit]
After=network-online.target

[Service]
User=ec2-user
WorkingDirectory={REMOTE_DIR}
Environment=INSTANCE_ID={instance['instance_id']}
Environment=CLUSTER_NAME={instance['cluster']}
ExecStart={REMOTE_DIR}/.venv/bin/uvicorn {app} --host 0.0.0.0 --port {APP_PORT}
Restart=always

[Install]
WantedBy=multi-user.target
EOF
sudo systemctl daemon-reload
sudo systemctl enable --now assignment1
"""
    subprocess.run(["ssh", *SSH_OPTIONS, host, setup], check=True)
    print(f"[{instance['instance_id']}] Done")


def deploy_apps():
    instances = get_project_instances()
    with ThreadPoolExecutor(max_workers=len(instances)) as executor:
        list(executor.map(deploy_instance, instances))

    lb_ip = next(i["public_ip"] for i in instances if i["cluster"] == LOADBALANCER["name"])
    print(f"Custom load balancer: http://{lb_ip}:{APP_PORT}")

    #This is used in the benchmark script
    return lb_ip


if __name__ == "__main__":
    deploy_apps()

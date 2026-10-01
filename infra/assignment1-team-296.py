"""Run the whole lab end-to-end: provision, deploy, ALB, then benchmark both load balancers."""

import asyncio

from alb import setup_alb
from benchmark import benchmark_clusters
from config import APP_PORT
from deploy import deploy_apps, ec2, get_project_instances
from provision import provision_instances


def wait_for_ssh_ready():
    # "running" doesn't mean sshd is up yet; status checks passing is a safe signal.
    instance_ids = [instance["instance_id"] for instance in get_project_instances()]
    print("Waiting for instance status checks (SSH readiness)...")
    ec2.get_waiter("instance_status_ok").wait(InstanceIds=instance_ids)


if __name__ == "__main__":
    provision_instances()
    wait_for_ssh_ready()
    lb_ip = deploy_apps()
    alb_dns = setup_alb()

    print("\nBenchmark: AWS ALB")
    asyncio.run(benchmark_clusters(alb_dns))

    print("\nBenchmark: custom load balancer")
    asyncio.run(benchmark_clusters(f"{lb_ip}:{APP_PORT}"))

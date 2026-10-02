"""Run the whole lab end-to-end: provision, deploy, ALB, then benchmark both load balancers."""

from alb import setup_alb
from benchmark import benchmark_all
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

    benchmark_all(alb_dns, f"{lb_ip}:{APP_PORT}")

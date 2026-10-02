"""Delete everything the project created: ALB, target groups, instances, security group and key pair."""

import stat

import boto3

from alb import ALB_NAME, TARGET_GROUP_NAMES
from config import AWS_REGION, KEY_NAME, KEY_PATH, PROJECT_TAG, SECURITY_GROUP_NAME

ec2 = boto3.client("ec2", region_name=AWS_REGION)
elbv2 = boto3.client("elbv2", region_name=AWS_REGION)


def delete_alb():
    for alb in elbv2.describe_load_balancers()["LoadBalancers"]:
        if alb["LoadBalancerName"] == ALB_NAME:
            print("Deleting ALB:", ALB_NAME)
            elbv2.delete_load_balancer(LoadBalancerArn=alb["LoadBalancerArn"])
            elbv2.get_waiter("load_balancers_deleted").wait(LoadBalancerArns=[alb["LoadBalancerArn"]])

    # Target groups can only be deleted once the ALB using them is gone.
    for group in elbv2.describe_target_groups()["TargetGroups"]:
        if group["TargetGroupName"] in TARGET_GROUP_NAMES.values():
            print("Deleting target group:", group["TargetGroupName"])
            elbv2.delete_target_group(TargetGroupArn=group["TargetGroupArn"])


def terminate_instances():
    response = ec2.describe_instances(
        Filters=[
            {"Name": "tag:Project", "Values": [PROJECT_TAG]},
            {"Name": "instance-state-name", "Values": ["pending", "running", "stopping", "stopped"]},
        ]
    )
    instance_ids = [i["InstanceId"] for r in response["Reservations"] for i in r["Instances"]]
    if instance_ids:
        print("Terminating", len(instance_ids), "instance(s)")
        ec2.terminate_instances(InstanceIds=instance_ids)
        ec2.get_waiter("instance_terminated").wait(InstanceIds=instance_ids)


def teardown_all():
    delete_alb()
    terminate_instances()

    # The security group can only be deleted once no instance or ALB uses it.
    for group in ec2.describe_security_groups(
        Filters=[{"Name": "group-name", "Values": [SECURITY_GROUP_NAME]}]
    )["SecurityGroups"]:
        print("Deleting security group:", SECURITY_GROUP_NAME)
        ec2.delete_security_group(GroupId=group["GroupId"])

    print("Deleting key pair:", KEY_NAME)
    ec2.delete_key_pair(KeyName=KEY_NAME)
    if KEY_PATH.exists():
        KEY_PATH.chmod(stat.S_IRUSR | stat.S_IWUSR)  # make it writable: Windows refuses to delete read-only files
        KEY_PATH.unlink()


if __name__ == "__main__":
    teardown_all()

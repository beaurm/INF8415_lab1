"""Deletes this project's ALB, EC2 instances, security groups, and key pair."""

import os
import stat

import boto3
from botocore.exceptions import ClientError

from alb import ALB_NAME, ALB_SECURITY_GROUP_NAME, TARGET_GROUP_NAMES
from config import AWS_REGION, KEY_NAME, PROJECT_TAG, SECURITY_GROUP_NAME

ec2 = boto3.client("ec2", region_name=AWS_REGION)
elbv2 = boto3.client("elbv2", region_name=AWS_REGION)


def find_project_instance_ids():
    resp = ec2.describe_instances(
        Filters=[
            {"Name": "tag:Project", "Values": [PROJECT_TAG]},
            {"Name": "instance-state-name", "Values": ["pending", "running", "stopping", "stopped"]},
        ]
    )
    return [
        inst["InstanceId"]
        for reservation in resp["Reservations"]
        for inst in reservation["Instances"]
    ]


def terminate_instances(instance_ids):
    if not instance_ids:
        print("No instances found for this project.")
        return
    print("Terminating", len(instance_ids), "instance(s)")
    ec2.terminate_instances(InstanceIds=instance_ids)
    ec2.get_waiter("instance_terminated").wait(InstanceIds=instance_ids)
    print("Instances terminated")


def delete_load_balancer_resources():
    try:
        response = elbv2.describe_load_balancers(Names=[ALB_NAME])
    except ClientError as error:
        if error.response.get("Error", {}).get("Code") != "LoadBalancerNotFound":
            raise
        response = {"LoadBalancers": []}

    if response["LoadBalancers"]:
        load_balancer_arn = response["LoadBalancers"][0]["LoadBalancerArn"]
        listeners = elbv2.describe_listeners(LoadBalancerArn=load_balancer_arn)["Listeners"]
        for listener in listeners:
            print("Deleting ALB listener:", listener["ListenerArn"])
            elbv2.delete_listener(ListenerArn=listener["ListenerArn"])

        print("Deleting ALB:", ALB_NAME)
        elbv2.delete_load_balancer(LoadBalancerArn=load_balancer_arn)
        elbv2.get_waiter("load_balancers_deleted").wait(
            LoadBalancerArns=[load_balancer_arn]
        )
    else:
        print("No ALB found for this project.")

    for target_group_name in TARGET_GROUP_NAMES.values():
        try:
            groups = elbv2.describe_target_groups(Names=[target_group_name])["TargetGroups"]
        except ClientError as error:
            if error.response.get("Error", {}).get("Code") == "TargetGroupNotFound":
                continue
            raise
        for group in groups:
            print("Deleting target group:", target_group_name)
            elbv2.delete_target_group(TargetGroupArn=group["TargetGroupArn"])


def remove_alb_security_group_references():
    alb_groups = ec2.describe_security_groups(
        Filters=[{"Name": "group-name", "Values": [ALB_SECURITY_GROUP_NAME]}]
    )["SecurityGroups"]
    if not alb_groups:
        return
    alb_group_id = alb_groups[0]["GroupId"]

    app_groups = ec2.describe_security_groups(
        Filters=[{"Name": "group-name", "Values": [SECURITY_GROUP_NAME]}]
    )["SecurityGroups"]
    for group in app_groups:
        for permission in group["IpPermissions"]:
            matching_pairs = [
                {"GroupId": pair["GroupId"]}
                for pair in permission.get("UserIdGroupPairs", [])
                if pair.get("GroupId") == alb_group_id
            ]
            if not matching_pairs:
                continue

            revoke_permission = {"IpProtocol": permission["IpProtocol"]}
            if "FromPort" in permission:
                revoke_permission["FromPort"] = permission["FromPort"]
                revoke_permission["ToPort"] = permission["ToPort"]
            revoke_permission["UserIdGroupPairs"] = matching_pairs
            ec2.revoke_security_group_ingress(
                GroupId=group["GroupId"],
                IpPermissions=[revoke_permission],
            )


def delete_security_group():
    for group_name in (SECURITY_GROUP_NAME, ALB_SECURITY_GROUP_NAME):
        existing = ec2.describe_security_groups(
            Filters=[{"Name": "group-name", "Values": [group_name]}]
        )
        for sg in existing["SecurityGroups"]:
            print("Deleting security group:", group_name)
            ec2.delete_security_group(GroupId=sg["GroupId"])


def delete_key_pair():
    existing = ec2.describe_key_pairs(Filters=[{"Name": "key-name", "Values": [KEY_NAME]}])
    if existing["KeyPairs"]:
        print("Deleting key pair:", KEY_NAME)
        ec2.delete_key_pair(KeyName=KEY_NAME)

    key_path = f"{KEY_NAME}.pem"
    if os.path.exists(key_path):
        os.chmod(key_path, stat.S_IREAD | stat.S_IWRITE)
        os.remove(key_path)
        print("Removed local key:", key_path)


def main():
    delete_load_balancer_resources()
    terminate_instances(find_project_instance_ids())
    remove_alb_security_group_references()
    delete_security_group()
    delete_key_pair()


if __name__ == "__main__":
    main()

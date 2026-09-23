"""Terminates every instance this project created and cleans up the
security group and key pair. Run this whenever you're done for the day --
running instances keep costing money even if you're not connected to them.
"""

import os

import boto3

from config import KEY_NAME, PROJECT_TAG, SECURITY_GROUP_NAME

ec2 = boto3.client("ec2")


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


def delete_security_group():
    existing = ec2.describe_security_groups(
        Filters=[{"Name": "group-name", "Values": [SECURITY_GROUP_NAME]}]
    )
    for sg in existing["SecurityGroups"]:
        print("Deleting security group:", SECURITY_GROUP_NAME)
        ec2.delete_security_group(GroupId=sg["GroupId"])


def delete_key_pair():
    existing = ec2.describe_key_pairs(Filters=[{"Name": "key-name", "Values": [KEY_NAME]}])
    if existing["KeyPairs"]:
        print("Deleting key pair:", KEY_NAME)
        ec2.delete_key_pair(KeyName=KEY_NAME)

    key_path = f"{KEY_NAME}.pem"
    if os.path.exists(key_path):
        os.remove(key_path)
        print("Removed local key:", key_path)


def main():
    terminate_instances(find_project_instance_ids())
    delete_security_group()
    delete_key_pair()


if __name__ == "__main__":
    main()

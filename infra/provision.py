"""Creates the 9 EC2 instances for the lab (5x cluster1, 4x cluster2).

Safe to re-run: it checks for existing resources (by name/tag) before
creating new ones, so it won't launch duplicate instances.

No load balancer / target groups yet -- this step is just the instances,
so you can inspect them before we wire up anything else.
"""

import os
import sys

import boto3

from config import (
    APP_PORT,
    CLUSTER1,
    CLUSTER2,
    INSTANCE_PROFILE_NAME,
    KEY_NAME,
    PROJECT_TAG,
    SECURITY_GROUP_NAME,
)

ec2 = boto3.client("ec2")


def get_default_vpc_id():
    resp = ec2.describe_vpcs(Filters=[{"Name": "is-default", "Values": ["true"]}])
    vpcs = resp["Vpcs"]
    if not vpcs:
        sys.exit("No default VPC found in this region/account.")
    return vpcs[0]["VpcId"]


def ensure_key_pair():
    existing = ec2.describe_key_pairs(Filters=[{"Name": "key-name", "Values": [KEY_NAME]}])
    if existing["KeyPairs"]:
        print(f"Key pair '{KEY_NAME}' already exists, reusing it.")
        return

    print(f"Creating key pair '{KEY_NAME}'...")
    resp = ec2.create_key_pair(KeyName=KEY_NAME, KeyType="rsa", KeyFormat="pem")
    key_path = f"{KEY_NAME}.pem"
    with open(key_path, "w") as f:
        f.write(resp["KeyMaterial"])
    os.chmod(key_path, 0o400)
    print(f"Saved private key to {key_path} (chmod 400).")


def ensure_security_group(vpc_id):
    existing = ec2.describe_security_groups(
        Filters=[
            {"Name": "group-name", "Values": [SECURITY_GROUP_NAME]},
            {"Name": "vpc-id", "Values": [vpc_id]},
        ]
    )
    if existing["SecurityGroups"]:
        sg_id = existing["SecurityGroups"][0]["GroupId"]
        print(f"Security group '{SECURITY_GROUP_NAME}' already exists ({sg_id}), reusing it.")
        return sg_id

    print(f"Creating security group '{SECURITY_GROUP_NAME}'...")
    resp = ec2.create_security_group(
        GroupName=SECURITY_GROUP_NAME,
        Description="INF8415 lab1 - SSH + FastAPI app port",
        VpcId=vpc_id,
    )
    sg_id = resp["GroupId"]
    ec2.authorize_security_group_ingress(
        GroupId=sg_id,
        IpPermissions=[
            {
                "IpProtocol": "tcp",
                "FromPort": 22,
                "ToPort": 22,
                "IpRanges": [{"CidrIp": "0.0.0.0/0", "Description": "SSH"}],
            },
            {
                "IpProtocol": "tcp",
                "FromPort": APP_PORT,
                "ToPort": APP_PORT,
                "IpRanges": [{"CidrIp": "0.0.0.0/0", "Description": "FastAPI app"}],
            },
        ],
    )
    return sg_id


def latest_al2023_ami(arch):
    resp = ec2.describe_images(
        Owners=["amazon"],
        Filters=[
            {"Name": "name", "Values": [f"al2023-ami-*-{arch}"]},
            {"Name": "state", "Values": ["available"]},
        ],
    )
    images = sorted(resp["Images"], key=lambda i: i["CreationDate"], reverse=True)
    if not images:
        sys.exit(f"No Amazon Linux 2023 AMI found for arch={arch}")
    return images[0]["ImageId"]


def existing_instance_ids(cluster_name):
    resp = ec2.describe_instances(
        Filters=[
            {"Name": "tag:Project", "Values": [PROJECT_TAG]},
            {"Name": "tag:Cluster", "Values": [cluster_name]},
            {"Name": "instance-state-name", "Values": ["pending", "running"]},
        ]
    )
    return [
        inst["InstanceId"]
        for reservation in resp["Reservations"]
        for inst in reservation["Instances"]
    ]


def launch_cluster(cluster, sg_id):
    name = cluster["name"]
    existing = existing_instance_ids(name)
    if existing:
        print(f"{name}: {len(existing)} instance(s) already running, skipping launch.")
        return existing

    ami_id = latest_al2023_ami(cluster["arch"])
    print(f"{name}: launching {cluster['count']}x {cluster['instance_type']} ({ami_id})...")

    resp = ec2.run_instances(
        ImageId=ami_id,
        InstanceType=cluster["instance_type"],
        MinCount=cluster["count"],
        MaxCount=cluster["count"],
        KeyName=KEY_NAME,
        SecurityGroupIds=[sg_id],
        IamInstanceProfile={"Name": INSTANCE_PROFILE_NAME},
        TagSpecifications=[
            {
                "ResourceType": "instance",
                "Tags": [
                    {"Key": "Project", "Value": PROJECT_TAG},
                    {"Key": "Cluster", "Value": name},
                    {"Key": "Name", "Value": f"{PROJECT_TAG}-{name}"},
                ],
            }
        ],
    )
    return [i["InstanceId"] for i in resp["Instances"]]


def main():
    vpc_id = get_default_vpc_id()
    ensure_key_pair()
    sg_id = ensure_security_group(vpc_id)

    all_ids = []
    for cluster in (CLUSTER1, CLUSTER2):
        all_ids += launch_cluster(cluster, sg_id)

    print("Waiting for instances to reach 'running' state...")
    ec2.get_waiter("instance_running").wait(InstanceIds=all_ids)

    resp = ec2.describe_instances(InstanceIds=all_ids)
    print(f"\n{'Instance ID':<20}{'Cluster':<12}{'Type':<12}Public IP")
    for reservation in resp["Reservations"]:
        for inst in reservation["Instances"]:
            tags = {t["Key"]: t["Value"] for t in inst.get("Tags", [])}
            print(
                f"{inst['InstanceId']:<20}{tags.get('Cluster', ''):<12}"
                f"{inst['InstanceType']:<12}{inst.get('PublicIpAddress', '-')}"
            )


if __name__ == "__main__":
    main()

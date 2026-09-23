#Program is idempotent to not create garbage duplicates accidently

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
    return vpcs[0]["VpcId"]

#Check or create key-pair
def ensure_key_pair():
    existing = ec2.describe_key_pairs(Filters=[{"Name": "key-name", "Values": [KEY_NAME]}])
    if existing["KeyPairs"]:
        print("Key pair already exists:", KEY_NAME)
        return

    print("Creating key pair:", KEY_NAME)
    resp = ec2.create_key_pair(KeyName=KEY_NAME, KeyType="rsa", KeyFormat="pem")
    key_path = f"{KEY_NAME}.pem"
    with open(key_path, "w") as f:
        f.write(resp["KeyMaterial"])
    os.chmod(key_path, 0o400)
    print("Saved private key:", key_path)

#Check or create security group
def ensure_security_group(vpc_id):
    existing = ec2.describe_security_groups(
        Filters=[
            {"Name": "group-name", "Values": [SECURITY_GROUP_NAME]},
            {"Name": "vpc-id", "Values": [vpc_id]},
        ]
    )
    if existing["SecurityGroups"]:
        sg_id = existing["SecurityGroups"][0]["GroupId"]
        print("Security group already exists:", SECURITY_GROUP_NAME)
        return sg_id

    print("Creating security group:", SECURITY_GROUP_NAME)
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
                #SSH
                "IpProtocol": "tcp",
                "FromPort": 22,
                "ToPort": 22,
                "IpRanges": [{"CidrIp": "0.0.0.0/0", "Description": "SSH"}],
            },
            {
                #FastIP script
                "IpProtocol": "tcp",
                "FromPort": APP_PORT,
                "ToPort": APP_PORT,
                "IpRanges": [{"CidrIp": "0.0.0.0/0", "Description": "FastAPI app"}],
            },
        ],
    )
    return sg_id

#Get existing_instance_ids (if any exist with project tag)
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


#Launch cluster and create instances if they dont exist
def launch_cluster(cluster, sg_id):
    name = cluster["name"]
    existing = existing_instance_ids(name)
    if existing:
        print(name, "already has", len(existing), "instance(s)")
        return existing

    ami_id = cluster["ami"]
    print("Launching", cluster["count"], cluster["instance_type"], "instance(s) for", name)

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

    print("Waiting for instances...")
    ec2.get_waiter("instance_running").wait(InstanceIds=all_ids)

    resp = ec2.describe_instances(InstanceIds=all_ids)
    for reservation in resp["Reservations"]:
        for inst in reservation["Instances"]:
            tags = {t["Key"]: t["Value"] for t in inst.get("Tags", [])}
            print(inst["InstanceId"], tags.get("Cluster", ""), inst["InstanceType"], inst.get("PublicIpAddress", "-"))


if __name__ == "__main__":
    main()

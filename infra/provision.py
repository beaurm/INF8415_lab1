#Program is idempotent to not create garbage duplicates accidently

import os
import sys

import boto3
from botocore.exceptions import BotoCoreError, ClientError

from config import (
    APP_PORT,
    AWS_REGION,
    CLUSTER1,
    CLUSTER2,
    INSTANCE_PROFILE_NAME,
    KEY_NAME,
    PROJECT_TAG,
    SECURITY_GROUP_NAME,
)

ec2 = boto3.client("ec2", region_name=AWS_REGION)


def get_default_vpc_id():
    resp = ec2.describe_vpcs(Filters=[{"Name": "is-default", "Values": ["true"]}])
    vpcs = resp["Vpcs"]
    return vpcs[0]["VpcId"]

#Check or create key-pair
def ensure_key_pair(created_resources):
    existing = ec2.describe_key_pairs(Filters=[{"Name": "key-name", "Values": [KEY_NAME]}])
    if existing["KeyPairs"]:
        print("Key pair already exists:", KEY_NAME)
        return

    print("Creating key pair:", KEY_NAME)
    resp = ec2.create_key_pair(KeyName=KEY_NAME, KeyType="rsa", KeyFormat="pem")
    key_path = f"{KEY_NAME}.pem"
    created_resources["key_pair_created"] = True
    created_resources["local_key_path"] = key_path
    with open(key_path, "w") as f:
        f.write(resp["KeyMaterial"])
    os.chmod(key_path, 0o400)
    print("Saved private key:", key_path)

#Check or create security group
def ensure_security_group(vpc_id, created_resources):
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
    created_resources["security_group_id"] = sg_id
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
def launch_cluster(cluster, sg_id, created_resources):
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
    instance_ids = [i["InstanceId"] for i in resp["Instances"]]
    created_resources["instance_ids"].extend(instance_ids)
    return instance_ids


def cleanup_created_resources(created_resources):
    instance_ids = created_resources["instance_ids"]
    instances_terminated = not instance_ids

    if instance_ids:
        try:
            print("Rolling back", len(instance_ids), "new instance(s)")
            ec2.terminate_instances(InstanceIds=instance_ids)
            ec2.get_waiter("instance_terminated").wait(InstanceIds=instance_ids)
            instances_terminated = True
        except Exception as error:
            print("Rollback could not terminate new instances:", error)

    if not instances_terminated:
        print("Keeping the new security group and key pair because instances may still use them.")
        return

    security_group_id = created_resources["security_group_id"]
    if security_group_id:
        try:
            ec2.delete_security_group(GroupId=security_group_id)
            print("Removed newly created security group:", security_group_id)
        except Exception as error:
            print("Rollback could not delete security group:", error)

    if created_resources["key_pair_created"]:
        try:
            ec2.delete_key_pair(KeyName=KEY_NAME)
            print("Removed newly created key pair:", KEY_NAME)
        except Exception as error:
            print("Rollback could not delete key pair:", error)
            return

        key_path = created_resources["local_key_path"]
        if key_path and os.path.exists(key_path):
            try:
                os.remove(key_path)
                print("Removed local key:", key_path)
            except OSError as error:
                print("Rollback could not remove local key:", error)


def main():
    created_resources = {
        "instance_ids": [],
        "security_group_id": None,
        "key_pair_created": False,
        "local_key_path": None,
    }

    try:
        vpc_id = get_default_vpc_id()
        ensure_key_pair(created_resources)
        sg_id = ensure_security_group(vpc_id, created_resources)

        all_ids = []
        for cluster in (CLUSTER1, CLUSTER2):
            all_ids += launch_cluster(cluster, sg_id, created_resources)

        print("Waiting for instances...")
        ec2.get_waiter("instance_running").wait(InstanceIds=all_ids)

        resp = ec2.describe_instances(InstanceIds=all_ids)
        for reservation in resp["Reservations"]:
            for inst in reservation["Instances"]:
                tags = {t["Key"]: t["Value"] for t in inst.get("Tags", [])}
                print(inst["InstanceId"], tags.get("Cluster", ""), inst["InstanceType"], inst.get("PublicIpAddress", "-"))
    except KeyboardInterrupt:
        print("\nProvisioning interrupted; rolling back resources created by this run.")
        cleanup_created_resources(created_resources)
        raise SystemExit(130)
    except Exception as error:
        if isinstance(error, ClientError):
            details = error.response.get("Error", {})
            print(f"AWS provisioning failed [{details.get('Code', 'ClientError')}]: {details.get('Message', error)}")
        elif isinstance(error, BotoCoreError):
            print("AWS provisioning failed:", error)
        else:
            print("Provisioning failed:", error)
        print("Rolling back resources created by this run.")
        cleanup_created_resources(created_resources)
        raise SystemExit(1) from error


if __name__ == "__main__":
    main()

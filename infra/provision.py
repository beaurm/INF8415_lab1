"""Create the key pair, security group and EC2 instances for both clusters and the custom LB."""

import stat

import boto3

from config import (
    APP_PORT,
    AWS_REGION,
    CLUSTER1,
    CLUSTER2,
    INSTANCE_PROFILE_NAME,
    KEY_NAME,
    KEY_PATH,
    LOADBALANCER,
    PROJECT_TAG,
    SECURITY_GROUP_NAME,
)

ec2 = boto3.client("ec2", region_name=AWS_REGION)


def create_key_pair():
    key = ec2.create_key_pair(KeyName=KEY_NAME)
    KEY_PATH.write_text(key["KeyMaterial"])
    KEY_PATH.chmod(stat.S_IRUSR)  # read-only for the owner: ssh refuses keys other users can read
    print("Saved private key:", KEY_PATH)


def create_security_group():
    # Shared by the instances and the ALB: SSH, HTTP for the ALB, and the app / custom LB port
    sg_id = ec2.create_security_group(
        GroupName=SECURITY_GROUP_NAME,
        Description="SSH, HTTP and FastAPI app port",
    )["GroupId"]
    ec2.authorize_security_group_ingress(
        GroupId=sg_id,
        IpPermissions=[
            {"IpProtocol": "tcp", "FromPort": port, "ToPort": port, "IpRanges": [{"CidrIp": "0.0.0.0/0"}]}
            for port in (22, 80, APP_PORT)
        ],
    )
    return sg_id


def launch_instances(cluster, sg_id):
    print("Launching", cluster["count"], cluster["instance_type"], "instance(s) for", cluster["name"])
    response = ec2.run_instances(
        ImageId=cluster["ami"],
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
                    {"Key": "Cluster", "Value": cluster["name"]},
                    {"Key": "Name", "Value": f"{PROJECT_TAG}-{cluster['name']}"},
                ],
            }
        ],
    )
    return [instance["InstanceId"] for instance in response["Instances"]]


def provision_instances():
    create_key_pair()
    sg_id = create_security_group()

    instance_ids = []
    for cluster in (CLUSTER1, CLUSTER2, LOADBALANCER):
        instance_ids += launch_instances(cluster, sg_id)

    print("Waiting for instances to be running...")
    ec2.get_waiter("instance_running").wait(InstanceIds=instance_ids)


if __name__ == "__main__":
    provision_instances()

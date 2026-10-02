"""Create the ALB with one target group per cluster and path-based routing (/cluster1, /cluster2)."""

import boto3

from config import APP_PORT, AWS_REGION, CLUSTER1, CLUSTER2, PROJECT_TAG, SECURITY_GROUP_NAME, TEAM_SEED
from deploy import get_project_instances

ec2 = boto3.client("ec2", region_name=AWS_REGION)
elbv2 = boto3.client("elbv2", region_name=AWS_REGION)

ALB_NAME = f"{PROJECT_TAG}-alb"
TARGET_GROUP_NAMES = {
    CLUSTER1["name"]: f"a1-{TEAM_SEED}-cluster1",
    CLUSTER2["name"]: f"a1-{TEAM_SEED}-cluster2",
}


def create_target_group(cluster, vpc_id, instance_ids):
    # The ALB checks /health every 15 s; 2 failures in a row mark an instance unhealthy.
    target_group_arn = elbv2.create_target_group(
        Name=TARGET_GROUP_NAMES[cluster],
        Protocol="HTTP",
        Port=APP_PORT,
        VpcId=vpc_id,
        HealthCheckPath="/health",
        HealthCheckIntervalSeconds=15,
        HealthyThresholdCount=2,
        UnhealthyThresholdCount=2,
    )["TargetGroups"][0]["TargetGroupArn"]
    elbv2.register_targets(
        TargetGroupArn=target_group_arn,
        Targets=[{"Id": instance_id} for instance_id in instance_ids],
    )
    return target_group_arn


def setup_alb():
    # An ALB needs subnets in at least two availability zones; the default VPC has one public subnet per zone.
    subnets = ec2.describe_subnets(Filters=[{"Name": "default-for-az", "Values": ["true"]}])["Subnets"]
    vpc_id = subnets[0]["VpcId"]
    sg_id = ec2.describe_security_groups(
        Filters=[{"Name": "group-name", "Values": [SECURITY_GROUP_NAME]}]
    )["SecurityGroups"][0]["GroupId"]

    alb = elbv2.create_load_balancer(
        Name=ALB_NAME,
        Subnets=[subnet["SubnetId"] for subnet in subnets],
        SecurityGroups=[sg_id],
    )["LoadBalancers"][0]

    # Paths that match no rule get a 404 instead of reaching an instance.
    listener_arn = elbv2.create_listener(
        LoadBalancerArn=alb["LoadBalancerArn"],
        Protocol="HTTP",
        Port=80,
        DefaultActions=[{"Type": "fixed-response", "FixedResponseConfig": {"StatusCode": "404"}}],
    )["Listeners"][0]["ListenerArn"]

    instances = get_project_instances()
    target_group_arns = []
    for priority, cluster in enumerate(TARGET_GROUP_NAMES, start=1):
        instance_ids = [i["instance_id"] for i in instances if i["cluster"] == cluster]
        target_group_arn = create_target_group(cluster, vpc_id, instance_ids)
        elbv2.create_rule(
            ListenerArn=listener_arn,
            Priority=priority,
            Conditions=[{"Field": "path-pattern", "Values": [f"/{cluster}*"]}],
            Actions=[{"Type": "forward", "TargetGroupArn": target_group_arn}],
        )
        target_group_arns.append(target_group_arn)

    print("Waiting for the ALB and its targets to be ready...")
    elbv2.get_waiter("load_balancer_available").wait(LoadBalancerArns=[alb["LoadBalancerArn"]])
    for target_group_arn in target_group_arns:
        elbv2.get_waiter("target_in_service").wait(TargetGroupArn=target_group_arn)

    print("ALB DNS:", alb["DNSName"])
    return alb["DNSName"]


if __name__ == "__main__":
    setup_alb()

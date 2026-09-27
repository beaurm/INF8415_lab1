"""Create or reconcile the AWS ALB and route each cluster by path."""

import json
import time
from urllib.error import URLError
from urllib.request import urlopen

import boto3
from botocore.exceptions import BotoCoreError, ClientError

from config import (
    APP_PORT,
    AWS_REGION,
    CLUSTER1,
    CLUSTER2,
    PROJECT_TAG,
    TEAM_SEED,
)

ec2 = boto3.client("ec2", region_name=AWS_REGION)
elbv2 = boto3.client("elbv2", region_name=AWS_REGION)

ALB_NAME = f"{PROJECT_TAG}-alb"
ALB_SECURITY_GROUP_NAME = f"{PROJECT_TAG}-alb-sg"
TARGET_GROUP_NAMES = {
    CLUSTER1["name"]: f"a1-{TEAM_SEED}-cluster1",
    CLUSTER2["name"]: f"a1-{TEAM_SEED}-cluster2",
}
EXPECTED_COUNTS = {CLUSTER1["name"]: CLUSTER1["count"], CLUSTER2["name"]: CLUSTER2["count"]}


def get_default_vpc():
    response = ec2.describe_vpcs(Filters=[{"Name": "is-default", "Values": ["true"]}])
    vpcs = response["Vpcs"]
    if len(vpcs) != 1:
        raise RuntimeError(f"Expected one default VPC, found {len(vpcs)}")
    return vpcs[0]["VpcId"]


def get_public_subnets(vpc_id, instances):
    response = ec2.describe_subnets(
        Filters=[
            {"Name": "vpc-id", "Values": [vpc_id]},
            {"Name": "state", "Values": ["available"]},
        ]
    )
    by_zone = {}
    for subnet in response["Subnets"]:
        if subnet.get("MapPublicIpOnLaunch"):
            by_zone.setdefault(subnet["AvailabilityZone"], subnet["SubnetId"])

    target_zones = {item["availability_zone"] for item in instances}
    missing_zones = target_zones - by_zone.keys()
    if missing_zones:
        raise RuntimeError(f"No public subnet found for target availability zones: {sorted(missing_zones)}")
    if len(by_zone) < 2:
        raise RuntimeError("The default VPC must have public subnets in at least two availability zones")

    selected_zones = sorted(target_zones)
    if len(selected_zones) == 1:
        selected_zones.extend(zone for zone in sorted(by_zone) if zone not in target_zones)
        selected_zones = selected_zones[:2]
    return [by_zone[zone] for zone in selected_zones]


def get_project_instances():
    paginator = ec2.get_paginator("describe_instances")
    pages = paginator.paginate(
        Filters=[
            {"Name": "tag:Project", "Values": [PROJECT_TAG]},
            {"Name": "instance-state-name", "Values": ["running"]},
        ]
    )

    instances = []
    security_group_ids = set()
    for page in pages:
        for reservation in page["Reservations"]:
            for instance in reservation["Instances"]:
                tags = {tag["Key"]: tag["Value"] for tag in instance.get("Tags", [])}
                cluster = tags.get("Cluster")
                if cluster not in EXPECTED_COUNTS:
                    raise RuntimeError(f"Unexpected cluster tag on {instance['InstanceId']}: {cluster}")
                instances.append(
                    {
                        "instance_id": instance["InstanceId"],
                        "cluster": cluster,
                        "availability_zone": instance["Placement"]["AvailabilityZone"],
                    }
                )
                security_group_ids.update(sg["GroupId"] for sg in instance.get("SecurityGroups", []))

    counts = {name: sum(item["cluster"] == name for item in instances) for name in EXPECTED_COUNTS}
    if counts != EXPECTED_COUNTS:
        raise RuntimeError(f"Expected running instances {EXPECTED_COUNTS}, found {counts}")
    if not security_group_ids:
        raise RuntimeError("No security groups are attached to the project instances")

    return sorted(instances, key=lambda item: (item["cluster"], item["instance_id"])), sorted(security_group_ids)


def ensure_alb_security_group(vpc_id):
    response = ec2.describe_security_groups(
        Filters=[
            {"Name": "group-name", "Values": [ALB_SECURITY_GROUP_NAME]},
            {"Name": "vpc-id", "Values": [vpc_id]},
        ]
    )
    if response["SecurityGroups"]:
        group = response["SecurityGroups"][0]
        print("Reusing ALB security group:", group["GroupId"])
    else:
        response = ec2.create_security_group(
            GroupName=ALB_SECURITY_GROUP_NAME,
            Description=f"Public HTTP ingress for {PROJECT_TAG} ALB",
            VpcId=vpc_id,
            TagSpecifications=[
                {
                    "ResourceType": "security-group",
                    "Tags": [
                        {"Key": "Project", "Value": PROJECT_TAG},
                        {"Key": "TeamSeed", "Value": str(TEAM_SEED)},
                    ],
                }
            ],
        )
        group = {"GroupId": response["GroupId"], "IpPermissions": []}
        print("Created ALB security group:", group["GroupId"])

    has_http_ingress = any(
        permission.get("IpProtocol") == "tcp"
        and permission.get("FromPort") == 80
        and any(item.get("CidrIp") == "0.0.0.0/0" for item in permission.get("IpRanges", []))
        for permission in group["IpPermissions"]
    )
    if not has_http_ingress:
        ec2.authorize_security_group_ingress(
            GroupId=group["GroupId"],
            IpPermissions=[
                {
                    "IpProtocol": "tcp",
                    "FromPort": 80,
                    "ToPort": 80,
                    "IpRanges": [{"CidrIp": "0.0.0.0/0", "Description": "Public HTTP to ALB"}],
                }
            ],
        )
    return group["GroupId"]


def ensure_target_group(cluster, vpc_id):
    name = TARGET_GROUP_NAMES[cluster]
    try:
        response = elbv2.describe_target_groups(Names=[name])
        target_group = response["TargetGroups"][0]
        if target_group["VpcId"] != vpc_id or target_group["TargetType"] != "instance":
            raise RuntimeError(f"Existing target group {name} has incompatible VPC or target type")
        print(f"Reusing target group {name}:", target_group["TargetGroupArn"])
        elbv2.modify_target_group(
            TargetGroupArn=target_group["TargetGroupArn"],
            HealthCheckProtocol="HTTP",
            HealthCheckPort="traffic-port",
            HealthCheckPath="/health",
            HealthCheckEnabled=True,
            Matcher={"HttpCode": "200"},
        )
        return target_group["TargetGroupArn"]
    except ClientError as error:
        if error.response.get("Error", {}).get("Code") != "TargetGroupNotFound":
            raise

    response = elbv2.create_target_group(
        Name=name,
        Protocol="HTTP",
        Port=APP_PORT,
        VpcId=vpc_id,
        TargetType="instance",
        HealthCheckProtocol="HTTP",
        HealthCheckPort="traffic-port",
        HealthCheckPath="/health",
        HealthCheckEnabled=True,
        HealthCheckIntervalSeconds=15,
        HealthCheckTimeoutSeconds=5,
        HealthyThresholdCount=2,
        UnhealthyThresholdCount=2,
        Matcher={"HttpCode": "200"},
        Tags=[
            {"Key": "Project", "Value": PROJECT_TAG},
            {"Key": "TeamSeed", "Value": str(TEAM_SEED)},
            {"Key": "Cluster", "Value": cluster},
        ],
    )
    target_group = response["TargetGroups"][0]
    print(f"Created target group {name}:", target_group["TargetGroupArn"])
    return target_group["TargetGroupArn"]


def ensure_load_balancer(vpc_id, subnet_ids, security_group_id):
    try:
        response = elbv2.describe_load_balancers(Names=[ALB_NAME])
        load_balancer = response["LoadBalancers"][0]
        print("Reusing ALB:", load_balancer["LoadBalancerArn"])
        if load_balancer["VpcId"] != vpc_id:
            raise RuntimeError(f"Existing ALB {ALB_NAME} belongs to another VPC")
        if load_balancer["State"]["Code"] == "active":
            current_subnets = {zone["SubnetId"] for zone in load_balancer["AvailabilityZones"]}
            if current_subnets != set(subnet_ids):
                elbv2.set_subnets(
                    LoadBalancerArn=load_balancer["LoadBalancerArn"],
                    Subnets=subnet_ids,
                )
            elbv2.set_security_groups(
                LoadBalancerArn=load_balancer["LoadBalancerArn"],
                SecurityGroups=[security_group_id],
            )
        return load_balancer
    except ClientError as error:
        if error.response.get("Error", {}).get("Code") != "LoadBalancerNotFound":
            raise

    response = elbv2.create_load_balancer(
        Name=ALB_NAME,
        Subnets=subnet_ids,
        SecurityGroups=[security_group_id],
        Scheme="internet-facing",
        Type="application",
        IpAddressType="ipv4",
        Tags=[
            {"Key": "Project", "Value": PROJECT_TAG},
            {"Key": "TeamSeed", "Value": str(TEAM_SEED)},
        ],
    )
    load_balancer = response["LoadBalancers"][0]
    print("Created ALB:", load_balancer["LoadBalancerArn"])
    elbv2.get_waiter("load_balancer_available").wait(
        LoadBalancerArns=[load_balancer["LoadBalancerArn"]]
    )
    return load_balancer


def ensure_listener(load_balancer_arn):
    response = elbv2.describe_listeners(LoadBalancerArn=load_balancer_arn)
    for listener in response["Listeners"]:
        if listener["Port"] == 80 and listener["Protocol"] == "HTTP":
            return listener["ListenerArn"]

    response = elbv2.create_listener(
        LoadBalancerArn=load_balancer_arn,
        Protocol="HTTP",
        Port=80,
        DefaultActions=[
            {
                "Type": "fixed-response",
                "FixedResponseConfig": {
                    "StatusCode": "404",
                    "ContentType": "text/plain",
                    "MessageBody": "Route not found",
                },
            }
        ],
    )
    return response["Listeners"][0]["ListenerArn"]


def ensure_path_rule(listener_arn, path, target_group_arn):
    response = elbv2.describe_rules(ListenerArn=listener_arn)
    rules = [rule for rule in response["Rules"] if rule["Priority"] != "default"]

    for rule in rules:
        for condition in rule.get("Conditions", []):
            values = condition.get("Values", [])
            values += condition.get("PathPatternConfig", {}).get("Values", [])
            if condition.get("Field") == "path-pattern" and path in values:
                elbv2.modify_rule(
                    RuleArn=rule["RuleArn"],
                    Conditions=[{"Field": "path-pattern", "Values": [path]}],
                    Actions=[{"Type": "forward", "TargetGroupArn": target_group_arn}],
                )
                return

    used_priorities = {int(rule["Priority"]) for rule in rules}
    priority = next(value for value in range(1, 50000) if value not in used_priorities)
    elbv2.create_rule(
        ListenerArn=listener_arn,
        Priority=priority,
        Conditions=[{"Field": "path-pattern", "Values": [path]}],
        Actions=[{"Type": "forward", "TargetGroupArn": target_group_arn}],
    )


def restrict_instance_port(security_group_ids, alb_security_group_id):
    for group_id in security_group_ids:
        group = ec2.describe_security_groups(GroupIds=[group_id])["SecurityGroups"][0]
        has_alb_source = any(
            permission.get("IpProtocol") == "tcp"
            and permission.get("FromPort") == APP_PORT
            and permission.get("ToPort") == APP_PORT
            and any(
                pair.get("GroupId") == alb_security_group_id
                for pair in permission.get("UserIdGroupPairs", [])
            )
            for permission in group["IpPermissions"]
        )
        if not has_alb_source:
            ec2.authorize_security_group_ingress(
                GroupId=group_id,
                IpPermissions=[
                    {
                        "IpProtocol": "tcp",
                        "FromPort": APP_PORT,
                        "ToPort": APP_PORT,
                        "UserIdGroupPairs": [
                            {"GroupId": alb_security_group_id, "Description": "FastAPI traffic from ALB"}
                        ],
                    }
                ],
            )

        for permission in group["IpPermissions"]:
            if (
                permission.get("IpProtocol") != "tcp"
                or permission.get("FromPort") != APP_PORT
                or permission.get("ToPort") != APP_PORT
            ):
                continue
            for address in permission.get("IpRanges", []):
                if address.get("CidrIp") in ("0.0.0.0/0",):
                    ec2.revoke_security_group_ingress(
                        GroupId=group_id,
                        IpPermissions=[
                            {
                                "IpProtocol": "tcp",
                                "FromPort": APP_PORT,
                                "ToPort": APP_PORT,
                                "IpRanges": [{"CidrIp": address["CidrIp"]}],
                            }
                        ],
                    )


def register_cluster_targets(instances, target_group_arns):
    for cluster, target_group_arn in target_group_arns.items():
        expected_ids = {item["instance_id"] for item in instances if item["cluster"] == cluster}
        health = elbv2.describe_target_health(TargetGroupArn=target_group_arn)["TargetHealthDescriptions"]
        registered_ids = {item["Target"]["Id"] for item in health}
        stale_ids = registered_ids - expected_ids
        missing_ids = expected_ids - registered_ids

        if stale_ids:
            elbv2.deregister_targets(
                TargetGroupArn=target_group_arn,
                Targets=[{"Id": instance_id} for instance_id in sorted(stale_ids)],
            )
        if missing_ids:
            elbv2.register_targets(
                TargetGroupArn=target_group_arn,
                Targets=[{"Id": instance_id, "Port": APP_PORT} for instance_id in sorted(missing_ids)],
            )


def wait_for_healthy_targets(target_group_arns):
    deadline = time.monotonic() + 180
    while time.monotonic() < deadline:
        all_healthy = True
        for cluster, target_group_arn in target_group_arns.items():
            response = elbv2.describe_target_health(TargetGroupArn=target_group_arn)
            targets = response["TargetHealthDescriptions"]
            healthy = [item for item in targets if item["TargetHealth"]["State"] == "healthy"]
            print(f"{cluster}: {len(healthy)}/{EXPECTED_COUNTS[cluster]} healthy")
            if len(healthy) != EXPECTED_COUNTS[cluster]:
                all_healthy = False
        if all_healthy:
            return
        time.sleep(10)
    raise RuntimeError("Not all ALB targets became healthy within 180 seconds")


def verify_routing(dns_name, instances):
    targets = {cluster: {item["instance_id"] for item in instances if item["cluster"] == cluster}
               for cluster in EXPECTED_COUNTS}
    for cluster in EXPECTED_COUNTS:
        url = f"http://{dns_name}/{cluster}"
        with urlopen(url, timeout=10) as response:
            payload = json.loads(response.read().decode("utf-8"))
            seed_header = response.headers.get("X-Team-Seed")
        if (
            payload.get("cluster") != cluster
            or payload.get("instance_id") not in targets[cluster]
            or payload.get("team_seed") != TEAM_SEED
            or seed_header != str(TEAM_SEED)
        ):
            raise RuntimeError(f"ALB route {cluster} returned an unexpected response: {payload}")
        print(f"Verified /{cluster} -> {payload['instance_id']} (seed {seed_header})")


def main():
    try:
        vpc_id = get_default_vpc()
        instances, instance_security_group_ids = get_project_instances()
        subnet_ids = get_public_subnets(vpc_id, instances)
        alb_security_group_id = ensure_alb_security_group(vpc_id)
        target_group_arns = {
            cluster: ensure_target_group(cluster, vpc_id) for cluster in EXPECTED_COUNTS
        }
        load_balancer = ensure_load_balancer(vpc_id, subnet_ids, alb_security_group_id)
        load_balancer_arn = load_balancer["LoadBalancerArn"]
        listener_arn = ensure_listener(load_balancer_arn)

        for cluster, target_group_arn in target_group_arns.items():
            ensure_path_rule(listener_arn, f"/{cluster}*", target_group_arn)

        restrict_instance_port(instance_security_group_ids, alb_security_group_id)
        register_cluster_targets(instances, target_group_arns)
        wait_for_healthy_targets(target_group_arns)

        load_balancer = elbv2.describe_load_balancers(LoadBalancerArns=[load_balancer_arn])["LoadBalancers"][0]
        dns_name = load_balancer["DNSName"]
        verify_routing(dns_name, instances)
        print("ALB DNS:", dns_name)
        print("ALB setup completed successfully.")
    except (BotoCoreError, ClientError, URLError) as error:
        raise SystemExit(f"ALB setup failed: {error}. Existing AWS resources may need cleanup or a rerun.") from error
    except RuntimeError as error:
        raise SystemExit(f"ALB setup failed: {error}. Existing AWS resources may need cleanup or a rerun.") from error


if __name__ == "__main__":
    main()
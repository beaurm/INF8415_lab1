"""Shared config for the boto3 provisioning scripts."""

TEAM_SEED = 296
PROJECT_TAG = f"assignment1-team-{TEAM_SEED}"

KEY_NAME = f"{PROJECT_TAG}-key"
SECURITY_GROUP_NAME = f"{PROJECT_TAG}-sg"

APP_PORT = 8000
AWS_REGION = "us-east-1"

INSTANCE_PROFILE_NAME = "LabInstanceProfile"

CLUSTER1 = {
    "name": "cluster1",
    "instance_type": "t3.micro",
    "count": 4,
    "ami": "ami-0b2c9d1f3edcfd709",
}

CLUSTER2 = {
    "name": "cluster2",
    "instance_type": "t3.medium",
    "count": 4,
    "ami": "ami-0b2c9d1f3edcfd709",
}

LOADBALANCER = {
    "name": "loadbalancer",
    "instance_type": "t3.micro",
    "count": 1,
    "ami": "ami-0b2c9d1f3edcfd709",
}
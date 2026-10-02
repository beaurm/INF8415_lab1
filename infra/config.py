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
    "ami": "ami-0d27e0fb3bac4d724",
}

CLUSTER2 = {
    "name": "cluster2",
    "instance_type": "m7g.large",
    "count": 4,
    "ami": "ami-065b1b834d2a83a7a",
}

LOADBALANCER = {
    "name": "loadbalancer",
    "instance_type": "t3.micro",
    "count": 1,
    "ami": "ami-0d27e0fb3bac4d724",
}
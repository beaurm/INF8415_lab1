"""Shared config for the boto3 provisioning scripts."""

TEAM_SEED = 296  # sha256("2251271-2256783-2278089-2291231") % 10000, per Section 6.4
PROJECT_TAG = f"assignment1-team-{TEAM_SEED}"

KEY_NAME = f"{PROJECT_TAG}-key"
SECURITY_GROUP_NAME = f"{PROJECT_TAG}-sg"

APP_PORT = 8000

# AWS Academy Learner Lab provisions this instance profile for you automatically.
INSTANCE_PROFILE_NAME = "LabInstanceProfile"

CLUSTER1 = {
    "name": "cluster1",
    "instance_type": "t3.micro",
    "count": 5,
    "ami": "ami-0b2c9d1f3edcfd709",  # al2023-ami-2023.12.20260918.0-kernel-6.1-x86_64
}

CLUSTER2 = {
    "name": "cluster2",
    "instance_type": "m7g.large",
    "count": 4,
    "ami": "ami-007d8fad70c3dae04",  # al2023-ami-2023.12.20260918.0-kernel-6.1-arm64
}

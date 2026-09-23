"""Shared config for the boto3 provisioning scripts."""

# TODO: rename to "assignment1-team-<seed>" once the team seed is computed (Section 6.4).
PROJECT_TAG = "inf8415-lab1"

KEY_NAME = f"{PROJECT_TAG}-key"
SECURITY_GROUP_NAME = f"{PROJECT_TAG}-sg"

APP_PORT = 8000

# AWS Academy Learner Lab provisions this instance profile for you automatically.
INSTANCE_PROFILE_NAME = "LabInstanceProfile"

CLUSTER1 = {
    "name": "cluster1",
    "instance_type": "t3.micro",
    "count": 5,
    "arch": "x86_64",
}

CLUSTER2 = {
    "name": "cluster2",
    "instance_type": "m7g.large",
    "count": 4,
    "arch": "arm64",
}

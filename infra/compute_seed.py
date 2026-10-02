"""Compute the team seed and the custom LB failover threshold (Section 6.4)."""

import hashlib

STUDENT_IDS = ["2278089", "2251271", "2256783", "2291231"]


def compute_team_seed(student_ids):
    joined = "-".join(sorted(student_ids))
    return int(hashlib.sha256(joined.encode()).hexdigest(), 16) % 10000


if __name__ == "__main__":
    seed = compute_team_seed(STUDENT_IDS)
    print("Team seed:         ", seed)

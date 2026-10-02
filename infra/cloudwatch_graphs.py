"""Save recent ALB health and request graphs"""

from datetime import datetime, timedelta, timezone
import json
from pathlib import Path

import boto3

from alb import ALB_NAME, TARGET_GROUP_NAMES
from config import AWS_REGION, CLUSTER1, CLUSTER2


OUTPUT_DIR = Path(__file__).resolve().parents[1] / "cloudwatch"
LOOKBACK_MINUTES = 30
METRICS = (
    ("HealthyHostCount", "Minimum", "healthy-host-count", "Healthy targets"),
    ("RequestCountPerTarget", "Sum", "requests-per-target", "Requests per healthy target"),
)


def utc_label(timestamp):
    return timestamp.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def save_cloudwatch_graphs():
    elbv2 = boto3.client("elbv2", region_name=AWS_REGION)
    cloudwatch = boto3.client("cloudwatch", region_name=AWS_REGION)
    alb = elbv2.describe_load_balancers(Names=[ALB_NAME])["LoadBalancers"][0]
    alb_instance = alb["LoadBalancerArn"].split("loadbalancer/", 1)[1]
    end_time = datetime.now(timezone.utc)
    start = utc_label(end_time - timedelta(minutes=LOOKBACK_MINUTES))
    end = utc_label(end_time)
    OUTPUT_DIR.mkdir(exist_ok=True)

    for cluster in (CLUSTER1["name"], CLUSTER2["name"]):
        group = elbv2.describe_target_groups(Names=[TARGET_GROUP_NAMES[cluster]])["TargetGroups"][0]
        target_group = group["TargetGroupArn"].split(":")[-1]
        for metric_name, stat, filename, label in METRICS:
            widget = {
                "metrics": [[
                    "AWS/ApplicationELB", metric_name,
                    "LoadBalancer", alb_instance,
                    "TargetGroup", target_group,
                    {"stat": stat, "label": label},
                ]],
                "view": "timeSeries",
                "region": AWS_REGION,
                "period": 60,
                "start": start,
                "end": end,
                "title": f"{cluster} | {metric_name}",
                "width": 1200,
                "height": 400,
                "yAxis": {"left": {"min": 0}},
            }
            image = cloudwatch.get_metric_widget_image(
                MetricWidget=json.dumps(widget), OutputFormat="png"
            )["MetricWidgetImage"]
            path = OUTPUT_DIR / f"{cluster}-{filename}.png"
            path.write_bytes(image)
            print("Saved", path)


if __name__ == "__main__":
    save_cloudwatch_graphs()

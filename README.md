# INF8415 Lab 1

Load Balancer from Scratch. This repository provisions two EC2 clusters,
deploys a FastAPI app on every instance, puts an AWS Application Load Balancer (ALB) and our own custom load balancer in front of them, benchmarks both, and saves the CloudWatch graphs. Everything can be run with a single command.

## Configuration

All settings live in `infra/config.py`.

| Setting | Value |
|---|---|
| Region | `us-east-1` |
| Cluster 1 (`/cluster1`) | 4 × `t3.micro` |
| Cluster 2 (`/cluster2`) | 4 × `m7g.large` |
| Custom load balancer | 1 × `t3.micro`, port `8000` |
| Team seed | `296` |
| Custom LB failover threshold | 50 + (296 mod 200) = `146 ms` |

The seed was computed with `uv run python infra/compute_seed.py`.

Cluster 1 has 4 instances instead of the 5 in the assignment: the Learner Lab
allows 9 running instances, and the custom load balancer uses one of them.

## Repository layout

| File | Role |
|---|---|
| `main.py` | FastAPI app deployed on every instance (`/cluster1`, `/cluster2`, `/health`) |
| `infra/assignment1-team-296.py` | Runs the whole lab end-to-end |
| `infra/provision.py` | Creates the key pair, security group and EC2 instances |
| `infra/deploy.py` | Installs the FastAPI app on the clusters and the custom LB on its instance |
| `infra/alb.py` | Creates the ALB, the two target groups and the path routing rules |
| `infra/custom_load_balancer.py` | Our load balancer (active probing, deployed by `deploy.py`) |
| `infra/benchmark.py` | Sends 1000 concurrent requests to each cluster |
| `infra/cloudwatch_graphs.py` | Saves the ALB CloudWatch graphs as PNGs in `cloudwatch/` |
| `infra/teardown.py` | Deletes every AWS resource the project created |
| `infra/compute_seed.py` | Computes the team seed from our student IDs |
| `results/` | Saved outputs of past runs |

## 1. Setup

Requires Python 3.12+ and [`uv`](https://docs.astral.sh/uv/). From the
repository root, install the dependencies:

```bash
uv sync
```

Copy the Learner Lab credentials (**AWS Details -> AWS CLI**) into
`~/.aws/credentials`. They expire at the end of each lab session.

## 2. Run everything (single command)

```bash
mkdir -p results
uv run python -u infra/assignment1-team-296.py 2>&1 | tee "results/run-$(date +%F-%H%M).txt"
```

This runs, in order:

1. **Provision** the 9 instances, the key pair and the security group.
2. **Wait** until the instances pass their AWS status checks (SSH is ready).
3. **Deploy** the FastAPI app on the 8 cluster instances and the custom load
   balancer on its own instance.
4. **Create the ALB**, wait until all targets are healthy and check both routes.
5. **Benchmark** both clusters through the ALB, then through the custom LB.

A full run takes about 10 minutes. `tee` shows the output and also saves it in
`results/`. The infrastructure is **left running** at the end (it is needed for
the live demo); see step 5 to delete it.

At the end of the deploy and ALB steps, the script prints the two addresses to
test with:

```text
Load Balancer public IP: <custom-lb-ip>
ALB DNS: <alb-dns-name>
```

## 3. Run the steps one by one (optional)

Each script can also be run on its own:

```bash
uv run python infra/provision.py
uv run python infra/deploy.py      # wait 2-3 min after provisioning, until SSH is ready
uv run python infra/alb.py
uv run python infra/benchmark.py <alb-dns-name>
uv run python infra/benchmark.py <custom-lb-ip>:8000
```

- `provision.py` reuses project instances that are already `pending` or
  `running`; it does not restart stopped ones. It saves the SSH key as
  `assignment1-team-296-key.pem` at the repository root; keep it private.
- `deploy.py` prints `Deployment completed successfully on all instances.` only
  if every instance returns the right instance ID, cluster and seed (`team_seed`
  in the JSON body and `X-Team-Seed` header).
- `alb.py` can be rerun safely: it reuses resources that already exist.

## 4. Test the load balancers

Each response contains the instance ID, the cluster and `team_seed: 296`, plus
an `X-Team-Seed: 296` header.

```bash
curl -i "http://<alb-dns-name>/cluster1"
curl -i "http://<custom-lb-ip>:8000/cluster2"
```

The ALB spreads requests across the instances of the target group (round-robin),
so the instance ID changes between requests. The custom LB sends requests to the
fastest healthy instance of the cluster, so the instance ID stays the same until
it fails over.

### Custom load balancer behavior

Every 3 seconds, the custom LB lists the running instances of each cluster and
measures their `/health` response time. It keeps routing to the current instance
while it responds within 146 ms; otherwise it switches to the fastest healthy
instance. If a request fails because the instance went down between two checks,
it re-checks the instances immediately and retries the request once on another
instance.

### Chaos check (demo)

Keep a request loop running against each cluster, then stop or terminate one
instance per cluster from the EC2 console:

```bash
while true; do curl -s "http://<custom-lb-ip>:8000/cluster1"; echo; sleep 0.5; done
```

The loop should keep returning responses from the remaining instances.

### CloudWatch graphs

While the ALB still exists, save the graphs of the last 30 minutes (healthy
targets and requests per target, for each target group):

```bash
uv run python infra/cloudwatch_graphs.py
```

The PNGs are written to `cloudwatch/` and **overwrite** the previous ones; copy
them elsewhere first if you want to keep them.

## 5. Delete everything

Teardown is **destructive**: it deletes the ALB, listener, target groups, all
project EC2 instances, both security groups and the AWS key pair, and removes the
local `.pem` file. Your source code is not affected.

```bash
uv run python infra/teardown.py
```

Check the EC2 console afterwards to confirm nothing is left. To start again,
repeat from step 1.

## Security and costs

- The instances and the ALB are billed while they exist: run the teardown when
  you are done.
- Ports `22` (SSH) and `8000` (app and custom LB) are open to the internet.

# INF8415 Lab 1

This guide covers the workflow currently implemented in this repository:
provision EC2 instances, deploy FastAPI to them, create the ALB, test the
routes, and tear everything down at the end of the session.

> **Project status:** EC2 provisioning, FastAPI deployment, and the ALB are
> available in the scripts below. The benchmark and custom load balancer have
> not been implemented yet. There is not yet a single command that completes
> the entire lab.

## 1. Prerequisites

- An active AWS Academy Learner Lab session in `us-east-1`.
- Git Bash opened at the repository root (not the AWS browser terminal).
- Python 3.12 or newer.
- `uv` installed at `$HOME/.local/bin/uv.exe`.
- Git for Windows with `ssh`, `scp`, and `cygpath` available.
- Sufficient AWS budget: EC2, public IPv4 addresses, and the ALB may incur charges.

Set the path to `uv` and check it:

```bash
UV="$HOME/.local/bin/uv.exe"
"$UV" --version
```

If a version is printed, sync the project environment from `pyproject.toml` and
`uv.lock`:

```bash
"$UV" sync
```

Expected result: the `.venv` environment exists and the project dependencies
are installed. The project is configured for region `us-east-1`, with 5
`t3.micro` instances and 4 `m7g.large` instances, and team seed `296`.

## 2. Local AWS credentials

The boto3 scripts run on your computer. They do not automatically receive the
credentials from the AWS browser terminal.

1. Start the Learner Lab.
2. Open **AWS Details -> AWS CLI** and copy the complete block beginning with
   `[default]`.
3. Open the local credentials file, outside this repository:

```bash
mkdir -p "$HOME/.aws"
notepad.exe "$(cygpath -w "$HOME/.aws/credentials")"
```

Paste the full block and save it. It contains temporary keys and a session
token. Never put these values in the repository or share them. They expire
after a few hours; replace them from AWS Details when they expire.

Check that boto3 can reach AWS:

```bash
"$UV" run python -c "import boto3; boto3.client('sts', region_name='us-east-1').get_caller_identity(); print('AWS credentials: OK')"
```

Expected result: `AWS credentials: OK`. If credentials fail, do not run the
AWS scripts.

## 3. Provision EC2 instances

This step creates the instances, SSH key pair, and security group. After a
teardown, it creates **new** instances and a new key.

```bash
"$UV" run python infra/provision.py
```

Expected result: the instances reach `running`, then the script prints their
IDs, clusters, instance types, and public IP addresses. There should be 5 lines
for `cluster1 t3.micro` and 4 for `cluster2 m7g.large`. The file
`assignment1-team-296-key.pem` is created at the repository root; keep it private.

For each cluster, the script reuses project instances already in `pending` or
`running` state. It does not restart stopped instances. Do not rerun this script
unless you intend to create AWS resources.

## 4. Deploy FastAPI to all nine instances

Make sure all nine EC2 instances are `running`, the Learner Lab and credentials
are still valid, and `ssh`, `scp`, and the `.pem` file are available.

```bash
"$UV" run python infra/deploy.py
```

The script discovers instances by tags, installs Python 3.12 and FastAPI,
creates a virtual environment on every EC2 instance, copies `main.py`, configures
and enables the `systemd` service, then checks the cluster route. It prints
`Deployment completed successfully on all instances.` only if all nine checks pass.

Each checked response must contain the correct EC2 instance ID, cluster, and
`team_seed: 296`; the `X-Team-Seed` response header must also be `296`.

## 5. Create and verify the ALB

This step creates a public ALB, a dedicated security group, two target groups,
an HTTP listener, and routing rules. It waits for all nine instances to become
healthy. It also restricts EC2 port `8000` to traffic from the ALB security group.

```bash
"$UV" run python infra/alb.py
```

Expected output:

```text
cluster1: 5/5 healthy
cluster2: 4/4 healthy
Verified /cluster1 -> ... (seed 296)
Verified /cluster2 -> ... (seed 296)
ALB DNS: <public-ALB-name>
ALB setup completed successfully.
```

Copy the name printed after `ALB DNS:` and test each route in Git Bash:

```bash
ALB_DNS="<public-ALB-name>"
curl -i "http://${ALB_DNS}/cluster1"
```

Expected: status `200`, header `296`, and JSON containing `cluster: cluster1`
and `team_seed: 296`. Repeat for the other cluster:

```bash
curl -i "http://${ALB_DNS}/cluster2"
```

This response should contain `cluster: cluster2`. The ALB forwards each request
to an instance in the matching target group, so the instance ID may vary between
requests.

If ALB setup fails after creating resources, some resources may remain in AWS
and continue to incur charges. The script can be rerun; otherwise, use the
teardown below.

## 6. End the session and delete resources

Teardown is **destructive**. It deletes the ALB, listener, target groups, all
nine project EC2 instances, security groups, and AWS key pair; it also deletes
the local `.pem` file. Run it only if you intend to destroy the cluster:

```bash
"$UV" run python infra/teardown.py
```

Expected result: deletion messages, `Instances terminated`, and removal of the
local key. Check AWS to confirm that the project instances, ALB, and target
groups are gone. Your local source code is not deleted. To use AWS again later,
repeat steps 2 through 5; provisioning will create new instances and a new key.

## Security and costs

- EC2 instances incur charges while they exist and are running.
- The ALB is billed hourly; LCU processing and public IPv4 addresses may add
  charges.
- The current security group exposes SSH (`22`) publicly; restrict it to your
  IP address before leaving the infrastructure running for an extended period.
- After the ALB is created, the application on port `8000` is reachable only
  through the ALB. Use the ALB DNS name, not the instance IP addresses.
- Final charges depend on runtime, traffic, region, and Learner Lab credits.
  Check the AWS budget and run teardown after the session.
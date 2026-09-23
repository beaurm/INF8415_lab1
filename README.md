# INF8415 Lab 1

## AWS credentials (Learner Lab)

Each time you start a new Learner Lab session:

1. Open the lab, go to **AWS Details -> AWS CLI**.
2. Copy the whole block shown there (it's already formatted as `[default]` + keys).
3. Paste it directly into `~/.aws/credentials` (not in this repo), overwriting whatever's there.

Credentials expire after a few hours — redo this when AWS calls start failing with auth errors.

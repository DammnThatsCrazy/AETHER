# AETHER — Infrastructure Decommission Procedure

How to permanently remove an applied AWS resource from an Aether workspace.

This is the **only** sanctioned path to a destroy. It exists because the
profile-gating work in `profiles.tf` / `main.tf` makes it trivially easy to
turn a live data store off with a one-word edit, and a `count` that drops to
zero is a `terraform destroy` of that resource in everything but name.

---

## The rule

**Flipping a deployment-profile toggle must never auto-destroy applied stateful
infrastructure.**

Changing `deployment_profile`, `network_egress_mode`, or any `enable_*` local
is a *configuration* change. When such a change would remove an
already-applied stateful resource — Aurora, RDS, ElastiCache, MSK, Neptune,
DynamoDB tables, SQS queues holding messages, S3 buckets, KMS keys, Secrets
Manager secrets — the correct sequence is:

1. `terraform state rm` the resource, or add `removed { … lifecycle { destroy = false } }`,
   so the profile change plans clean **without** a destroy.
2. Run this decommission procedure against the now-unmanaged resource as a
   separate, explicitly approved change.

Never let step 1 and step 2 collapse into a single `terraform apply`. A profile
flip that shows `Plan: … 1 to destroy` on a data store is a **stop-the-line
event**, not a diff to skim.

`moved.tf` exists for the mirror-image hazard: adding `count` to a module
renames its state address, and without the `moved` blocks Terraform would plan
a destroy-and-recreate of the live MSK / ElastiCache / Neptune / RDS resources.
It covers fourteen addresses — the four gated root modules, the five dedicated-ML
resources inside `module.ecs`, the two inside `module.alb`, and the three VPC
data-store security groups. Do not delete those blocks until every workspace has
applied at least once.

### One-time migration hazard: the private default route

The NAT default route used to be an inline `route` block inside
`aws_route_table.private`. It is now a separate `aws_route.private_nat`
resource, counted independently, so a private route table can validly exist
with no egress path at all — which is what makes `network_egress_mode = "none"`
and `"public_ip"` possible.

`moved` cannot express this: an inline route block is an attribute, not an
addressable resource, so there is nothing to move *from*. On the **first** apply
against a workspace that already has NAT (production-scale, enterprise-isolated),
Terraform will therefore update the route table in place to drop the inline
route and separately create the `aws_route`. Those are two operations on the
live egress path, and Terraform does not guarantee their order.

Treat that first apply as a **maintenance window**, not a routine promotion:

1. Apply it on its own, not batched with other changes.
2. Expect a brief window in which private-subnet egress may be unavailable.
3. Verify afterwards that each private route table has exactly one
   `0.0.0.0/0` route pointing at the intended NAT Gateway — in `ha` mode, at
   the NAT in the *same* AZ.
4. Workspaces with `nat_mode = "none"` (staging, production-lean) are
   unaffected: they have no NAT today and none after.

### "Kept for rollback safety" must be time-bounded

Several modules in this root carry a comment of the form *"kept for rollback
safety, decommission after 72 h of clean prod metrics"*. An open-ended
retention window is a standing bill and a standing attack surface.

Every retained-for-rollback resource must have:

- a named owner,
- an explicit expiry date recorded in `config/implementation_ledger.yaml`,
- a decommission ticket opened on or before that date.

If the expiry passes without a decommission, the retention is no longer
rollback safety — it is unowned cost, and it must be escalated rather than
silently extended.

---

## Procedure

Work top to bottom. Do not skip a step because the resource "obviously" has no
users; steps 2 to 5 exist precisely to disprove that assumption.

### 1. State inventory

Record exactly what is being removed and what Terraform believes about it.

```bash
cd "AWS Deployment/aether-aws/terraform"
terraform state list | grep -F 'module.<name>'
terraform state show 'module.<name>[0].<resource>'
```

Capture the resource IDs, ARNs, creation dates and current sizing. Attach the
output to the decommission ticket.

### 2. Consumer identification

Enumerate every principal that can reach the resource:

- IAM policies and roles that name its ARN.
- Security-group rules whose source or destination is its security group.
- VPC endpoints, subnet routes and DNS records that resolve to it.
- Cross-account grants, KMS key policies, resource policies.

### 3. Code and configuration reference search

Search the whole repository, not just Terraform:

```bash
rg -n '<resource-name>|<arn-fragment>|<endpoint-hostname>' \
  --glob '!**/.terraform/**'
```

Cover application code, task definitions, Helm/compose files, CI workflows,
runbooks, dashboards, alarm definitions and the docs tree. A stale reference in
a runbook is a future outage.

### 4. Active environment-variable verification

Confirm no running task is still configured to use it:

```bash
aws ecs describe-task-definition --task-definition <family> \
  --query 'taskDefinition.containerDefinitions[].environment'
aws ecs describe-task-definition --task-definition <family> \
  --query 'taskDefinition.containerDefinitions[].secrets'
```

Check every service in the cluster, including the per-role runtime services,
not just the backend. Also check SSM parameters and Secrets Manager entries
that inject configuration at start-up.

### 5. Production metric check

Prove the resource is genuinely idle over a window long enough to include
weekly and monthly batch work — a minimum of 14 days, longer if the workload
has a monthly cycle.

Look at connection counts, request/operation counts, bytes in/out, and
consumer lag or queue depth. Zero CPU is not evidence of zero use.

### 6. Replacement service confirmation

Confirm the replacement is actually carrying the traffic:

- The replacement's metrics show the volume the old resource used to serve.
- Its error rate and latency are within SLO.
- It has its own alarms, backups and runbook entries.

### 7. Dual-read comparison

Where the resource holds data (not just capacity), run a period of dual reads
and compare results between old and new backends. Record the comparison window,
the sample size, and the mismatch rate. A non-zero mismatch rate blocks the
decommission until explained.

### 8. Snapshot and backup

Take a final, independently verified backup **before** anything is removed:

- RDS/Aurora: final snapshot, then confirm it is listed and `available`.
- Neptune: cluster snapshot.
- ElastiCache: final backup where the engine supports it.
- MSK: export retained topics if any message is still of record.
- DynamoDB: on-demand backup or PITR export to S3.
- S3: replicate or copy the prefix to an archive bucket.

Record the snapshot identifier, its region, its size and its retention expiry.
A snapshot nobody has verified is not a backup.

### 9. Rollback test

Restore the snapshot into a scratch environment and prove the restore works
end to end: the data is present, the application can connect, and a
representative query returns the expected result. Document the measured
restore time — that number is the real rollback budget.

### 10. Reviewed destroy-specific plan

Generate a plan scoped to the removal only, and read every line:

```bash
terraform plan -destroy \
  -target='module.<name>' \
  -var-file=profiles/<profile>.tfvars \
  -out=decommission.tfplan
terraform show -no-color decommission.tfplan > decommission-plan.txt
```

The plan must contain **only** the intended resources. Any collateral change —
a security group rule, a route, an IAM policy, an alarm — must be understood
and called out in the ticket before approval, not discovered during the apply.

### 11. Explicit approval

Two named approvers sign off on the ticket: the service owner and an
infrastructure reviewer. The approval references the plan artifact hash from
step 10, the snapshot identifiers from step 8, and the measured restore time
from step 9. Verbal or chat-only approval is not approval.

### 12. Apply the exact reviewed plan

Apply the saved plan file — never a freshly generated one:

```bash
terraform apply decommission.tfplan
```

Re-planning between approval and apply invalidates the review.

### 13. Removal verification

Confirm the resource is gone and that Terraform agrees:

```bash
terraform state list | grep -F 'module.<name>'   # expect no output
terraform plan -var-file=profiles/<profile>.tfvars  # expect no changes
```

Verify in the AWS console/API that the resource, its subnet groups, parameter
groups, KMS aliases and log groups are actually deleted rather than left
orphaned.

### 14. Health verification

Watch the platform for a full business cycle after the removal:

- Error rates, latency and saturation on the replacement path.
- Alarms: no new INSUFFICIENT_DATA alarms left pointing at a deleted dimension.
- Dashboards: no widgets rendering empty.
- Logs: no connection-refused or DNS-resolution errors naming the old endpoint.

### 15. Billing confirmation

Confirm the cost actually went away. Compare the AWS Cost Explorer daily figure
for the relevant service across the two weeks before and after removal, and
record the delta on the ticket. A decommission that does not reduce the bill
either did not complete or removed the wrong thing.

Close the ticket only after this number is recorded.

---

## Known constraints

### Shared `environment` across the three production-class profiles

`profiles/production-lean.tfvars`, `profiles/production-scale.tfvars` and
`profiles/enterprise-isolated.tfvars` do not set `environment`, so all three
inherit the root default `"production"`. Only `profiles/staging.tfvars` sets it
explicitly.

Resource names in this root are built from `"${var.project}-${var.environment}"`,
so the three production-class profiles generate **identical resource names**.
Consequences:

- They cannot be applied into the same AWS account and region simultaneously —
  the second apply collides on names such as the ECS cluster, ALB, log groups
  and S3 buckets.
- Switching an existing workspace's profile between them re-uses the same
  names, which is what makes `moved.tf` sufficient for the `count` migration
  but also means a profile switch is an in-place mutation of production, not a
  parallel stand-up.
- A blue/green or side-by-side comparison between two production-class profiles
  is not currently possible without a separate account, region or state.

This is recorded as a known constraint, not fixed here: changing the naming
scheme renames essentially every resource in the root, which is itself a
destroy-and-recreate of production and must go through this procedure. Any fix
belongs in its own change, with `moved` blocks for every affected address.

### Dead second Terraform tree

`terraform/environments/{dev,staging,production,demo}/` and
`AWS Deployment/main.tf` reference seven modules that do not exist in this
repository. They are not the deployment path and `terraform init` fails there.
Nothing in this procedure applies to them; see `README.md`.

# ⛔ DEAD TERRAFORM TREE — DO NOT USE

**This directory (`terraform/environments/{dev,staging,production,demo}/`) and
the top-level `AWS Deployment/main.tf` are a dead, non-functional second
Terraform tree.** They are kept only so their history and the docs that
reference them stay resolvable. **Nothing applies them and they are not the
deployment path.**

## Why it does not work

`terraform init` fails in every subdirectory here. Between them these
compositions reference **seven modules that do not exist in this repository**:

```
cloudfront   opensearch   dynamodb   sagemaker   api_gateway   iam   waf
```

`environments/demo/main.tf` is additionally not valid HCL. This tree describes a
six-account / five-VPC architecture that **Aether does not run**.

## Where the real deployment lives

The one live Terraform root is the parent directory:

```
AWS Deployment/aether-aws/terraform/
```

It is **profile-driven** — one AWS account, one region, one VPC, selected by a
single `deployment_profile` variable (`staging` | `production-lean` |
`production-scale` | `enterprise-isolated`, plus the `demo` / `preview`
ephemeral profiles). The live variable surface is `../variables.tf` plus
`../profiles/*.tfvars`.

| To… | Read |
|---|---|
| Deploy from scratch | [`../../SETUP.md`](../../SETUP.md) |
| Understand the live root | [`../README.md`](../README.md) |
| See what Aether actually runs on AWS | [`docs/AWS-DEPLOYMENT.md`](../../../../docs/AWS-DEPLOYMENT.md) (canonical) |

## Rules for this tree

Per `CLAUDE.md`, `AGENTS.md`, and `docs/AWS-DEPLOYMENT.md`:

- **Do not modify, extend, or "fix"** these compositions.
- **Do not copy patterns out of them** — they describe infrastructure that does
  not exist.
- If you are here because a README or search result pointed you at
  `environments/production`, that reference is stale — use the live root above.

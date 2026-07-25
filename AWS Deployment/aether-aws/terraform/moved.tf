# ============================================================================
# AETHER — State address migrations
#
# Adding `count` to a module changes its state address from `module.<name>` to
# `module.<name>[0]`. Without these blocks, an already-applied production-scale
# or enterprise-isolated workspace would read the old address as "no longer in
# configuration" and plan a DESTROY of the live cluster, followed by a CREATE
# of an identical one at the new address. For MSK, ElastiCache, Neptune and
# RDS that is a data-loss event, not a no-op refactor.
#
# `moved` makes the rename a state-only operation: the plan shows the resources
# unchanged and the address updated. Each block is a pure 1:1 rename, so it is
# safe on a workspace that never applied the module (Terraform ignores a moved
# block whose source address is absent from state).
#
# Do not delete these blocks until every workspace that predates the profile
# gating commit has been applied at least once. Deleting them early re-arms the
# destroy-and-recreate plan they exist to prevent. Intentional removal of any
# of these data stores goes through DECOMMISSION.md — never through a profile
# toggle and never through deleting a moved block.
# ============================================================================

moved {
  from = module.rds
  to   = module.rds[0]
}

moved {
  from = module.elasticache
  to   = module.elasticache[0]
}

moved {
  from = module.msk
  to   = module.msk[0]
}

moved {
  from = module.neptune
  to   = module.neptune[0]
}

# ----------------------------------------------------------------------------
# Dedicated ML serving — in-module address changes.
#
# The same `count` rename applies inside modules/ecs and modules/alb, where the
# dedicated aether-ml-serving resources are now gated on enable_dedicated_ml.
# production-scale and enterprise-isolated keep the dedicated ML service, so
# without these blocks a promotion on either profile would destroy and recreate
# a live service, its task definition, its log group, its autoscaling target
# and its ALB target group — dropping /v1/ml/* traffic for the duration.
#
# Both endpoints of each block share the same module prefix, which is what
# Terraform requires; declaring them here keeps every address migration this
# commit introduces in one reviewable place.
# ----------------------------------------------------------------------------

moved {
  from = module.ecs.aws_ecs_service.ml
  to   = module.ecs.aws_ecs_service.ml[0]
}

moved {
  from = module.ecs.aws_ecs_task_definition.ml
  to   = module.ecs.aws_ecs_task_definition.ml[0]
}

moved {
  from = module.ecs.aws_cloudwatch_log_group.ml
  to   = module.ecs.aws_cloudwatch_log_group.ml[0]
}

moved {
  from = module.ecs.aws_appautoscaling_target.ml
  to   = module.ecs.aws_appautoscaling_target.ml[0]
}

moved {
  from = module.ecs.aws_appautoscaling_policy.ml_cpu
  to   = module.ecs.aws_appautoscaling_policy.ml_cpu[0]
}

moved {
  from = module.alb.aws_lb_target_group.ml
  to   = module.alb.aws_lb_target_group.ml[0]
}

moved {
  from = module.alb.aws_lb_listener_rule.ml_serving
  to   = module.alb.aws_lb_listener_rule.ml_serving[0]
}

# --------------------------------------------------------------------------
# VPC data-store security groups
#
# These gained `count` so lean profiles carry no network policy for backends
# they never provision. Scale and enterprise still create all three, so
# without these blocks a promotion there would destroy and recreate security
# groups that live ENIs are attached to — a disruptive, and in the MSK case
# slow, replacement rather than a no-op address change.
# --------------------------------------------------------------------------

moved {
  from = module.vpc.aws_security_group.redis
  to   = module.vpc.aws_security_group.redis[0]
}

moved {
  from = module.vpc.aws_security_group.neptune
  to   = module.vpc.aws_security_group.neptune[0]
}

moved {
  from = module.vpc.aws_security_group.msk
  to   = module.vpc.aws_security_group.msk[0]
}

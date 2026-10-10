import { useNavigate } from "react-router-dom";
import {
  Badge,
  Button,
  Card,
  CardContent,
  CardHeader,
  CardTitle,
  useQuery,
} from "@aether/ui";
import type { NoesisResponsePayload } from "@aether/ui";
import { useAuth } from "@aether-app/features/auth";
import { api } from "@aether-app/lib/api/endpoints";
import { hasDecisionApprovalPermission } from "@aether-app/features/intelligence/decision-permissions";

export { hasDecisionApprovalPermission } from "@aether-app/features/intelligence/decision-permissions";

export function responseHasGovernedProposal(
  response: NoesisResponsePayload,
): boolean {
  if (
    response.evidence?.claims.some(
      (claim) => claim.claim_type === "recommendation",
    )
  )
    return true;
  return response.results.some((result) => {
    if (!result || typeof result !== "object") return false;
    const record = result as Record<string, unknown>;
    return (
      typeof record.recommendation_id === "string" ||
      record.type === "recommendation"
    );
  });
}

function traceSourceCount(response: NoesisResponsePayload): number {
  return response.evidence?.sources.length ?? 0;
}

/**
 * Aether-only governance handoff. Noesis can expose evidence and propose a
 * review route, but it cannot approve or dispatch an action from an opaque
 * natural-language response. The actual decision panel remains the canonical
 * approval/planning surface and enforces its own server-side policy.
 */
export function NoesisResponseGovernance({
  response,
}: {
  readonly response: NoesisResponsePayload;
}) {
  const navigate = useNavigate();
  const { user } = useAuth();
  const permissions = useQuery<unknown>({
    key: `security:decision-permissions:${user?.id ?? "anonymous"}`,
    fetcher: () => api.security.myPermissions(),
    staleTime: 60_000,
    enabled: Boolean(user?.id),
  });
  const hasTrace = Boolean(
    response.query_debug || response.scope_summary || response.evidence,
  );
  const hasProposal = responseHasGovernedProposal(response);
  const approvalPermission = hasDecisionApprovalPermission(permissions.data);

  return (
    <Card
      className="mb-3 border-accent/30 bg-surface-raised/70"
      data-testid="noesis-response-governance"
    >
      <CardHeader className="pb-2">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <CardTitle className="text-xs font-mono">
            Trace &amp; proposal review
          </CardTitle>
          <Badge variant={hasTrace ? "success" : "default"}>
            {hasTrace ? "Trace available" : "Trace unavailable"}
          </Badge>
        </div>
      </CardHeader>
      <CardContent className="space-y-2 text-xs">
        <details className="rounded border border-border-subtle bg-surface-sunken/50 px-3 py-2">
          <summary className="cursor-pointer font-mono text-text-secondary">
            Response trace
          </summary>
          <div className="mt-2 space-y-1 text-text-muted">
            <div>
              Intent:{" "}
              <span className="text-text-secondary">{response.intent}</span>
            </div>
            <div>
              Mode: <span className="text-text-secondary">{response.mode}</span>
            </div>
            <div>
              Evidence sources:{" "}
              <span className="text-text-secondary">
                {traceSourceCount(response)}
              </span>
            </div>
            {response.evidence?.sufficient === false && (
              <div className="text-warning">
                Evidence is insufficient for a governed recommendation.
              </div>
            )}
          </div>
        </details>

        {hasProposal ? (
          <div className="flex flex-wrap items-center gap-2 rounded border border-border-subtle px-3 py-2">
            <span className="text-text-secondary">
              A governed recommendation was returned.
            </span>
            {permissions.isLoading ? (
              <Badge variant="default">Resolving approval permission…</Badge>
            ) : null}
            {!permissions.isLoading && permissions.error ? (
              <Badge variant="warning">Approval permission unavailable</Badge>
            ) : null}
            {!permissions.isLoading &&
            !permissions.error &&
            permissions.data !== null ? (
              <Badge variant={approvalPermission ? "success" : "warning"}>
                {approvalPermission
                  ? "Approval permission resolved"
                  : "Read-only: approval permission absent"}
              </Badge>
            ) : null}
            <Button
              type="button"
              size="sm"
              variant="secondary"
              onClick={() => navigate("/")}
            >
              Review in Decision Intelligence
            </Button>
          </div>
        ) : (
          <p className="text-text-muted">
            No governed proposal was returned. Approval and execution controls
            remain unavailable for this response.
          </p>
        )}
      </CardContent>
    </Card>
  );
}

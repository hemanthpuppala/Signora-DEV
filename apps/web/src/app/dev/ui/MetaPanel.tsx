"use client";

import { useQuery } from "@tanstack/react-query";

import { api, unwrap } from "@/shared/api/client";
import { NetworkError, userMessage } from "@/shared/api/errors";
import { useMeta } from "@/shared/api/useMeta";
import { MetricGrid, MetricTile, Notice, StatusPill } from "@/shared/ui";

/**
 * Readiness answers 503 ``{"status": "unavailable"}`` when the API is up but not ready: a definite
 * answer to show as "Not ready". A proxy's bare 503 (API unreachable) still counts as no answer.
 */
async function fetchReadiness() {
  let result;
  try {
    result = await api.GET("/api/v1/health/ready");
  } catch (error) {
    throw new NetworkError(error);
  }
  if (result.response.status === 503 && result.error?.status === "unavailable") return result.error;
  return unwrap(Promise.resolve(result));
}

/** Development only (component gallery): reads /api/v1/meta and /api/v1/health/ready: proves browser -> Caddy -> API works end to end. */
export function MetaPanel() {
  const meta = useMeta();
  const ready = useQuery({
    queryKey: ["health", "ready"],
    queryFn: fetchReadiness,
  });

  // A network failure keeps retrying (no error state yet), so show the last failure while it does;
  // a definite API error ends in the error state.
  const failure = meta.error ?? meta.failureReason;
  if (failure) {
    return (
      <Notice tone="warning" title="API unreachable">
        {userMessage(failure)}
      </Notice>
    );
  }

  return (
    <MetricGrid>
      <MetricTile value={meta.data?.version ?? "…"} label="API version" />
      <MetricTile value={meta.data?.commit ?? "…"} label="Build" />
      <MetricTile
        value={
          ready.isPending ? (
            "…"
          ) : (
            <StatusPill
              status={ready.data?.status === "ok" ? "completed" : "declined"}
              label={ready.data?.status === "ok" ? "Ready" : "Not ready"}
            />
          )
        }
        label="Readiness"
      />
    </MetricGrid>
  );
}

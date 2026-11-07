"use client";

import { useQuery } from "@tanstack/react-query";

import { api, unwrap } from "@/shared/api/client";
import { userMessage } from "@/shared/api/errors";
import { MetricGrid, MetricTile, Notice, StatusPill } from "@/shared/ui";

/** Reads /api/v1/meta and /api/v1/health/ready: proves browser -> Caddy -> API works end to end. */
export function MetaPanel() {
  const meta = useQuery({
    queryKey: ["meta"],
    queryFn: () => unwrap(api.GET("/api/v1/meta")),
  });
  const ready = useQuery({
    queryKey: ["health", "ready"],
    queryFn: () => unwrap(api.GET("/api/v1/health/ready")),
  });

  if (meta.isError) {
    return (
      <Notice tone="warning" title="API unreachable">
        {userMessage(meta.error)}
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

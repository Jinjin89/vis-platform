import { useEffect, useRef } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  cancelAssistant,
  cancelPlotRun,
  getAssistantState,
  getPlotRun,
} from "../../api/client";
import type {
  AssistantTurnSnapshot,
  PlotResult,
  PlotRunSnapshot,
} from "../../api/schemas/plotRun";
import type { PlotRequestProgress } from "../../api/schemas/reports";
import type { PendingRequest } from "./pinpointHistory";

export type RequestOutcome =
  | { kind: "reply"; text: string }
  | { kind: "plot"; result: PlotResult; text: string | null }
  | { kind: "failed"; text: string }
  | { kind: "cancelled" };

const finished = new Set(["completed", "failed", "cancelled"]);
const poll = (query: { state: { data?: { status: string } } }) =>
  query.state.data && finished.has(query.state.data.status) ? false : 1000;

/** Follows a request through planning and any plot run until it has an outcome. */
export function usePinpointRequest(
  pending: PendingRequest | null,
  onOutcome: (outcome: RequestOutcome) => void,
) {
  const handler = useRef(onOutcome);
  handler.current = onOutcome;
  const delivered = useRef(new Set<string>());
  const turnPath = pending?.turn.links.status ?? null;
  const turn = useQuery({
    queryKey: ["pinpoint-turn", turnPath],
    queryFn: () => getAssistantState(turnPath!),
    enabled: Boolean(turnPath),
    refetchInterval: poll,
  });
  const plotRun = turn.data?.response?.plot_run ?? null;
  const run = useQuery({
    queryKey: ["pinpoint-run", plotRun?.links.status],
    queryFn: () => getPlotRun(plotRun!.links.status),
    enabled: Boolean(plotRun),
    refetchInterval: poll,
  });
  const outcome = describeOutcome(
    turn.data,
    run.data,
    turn.isError || run.isError,
  );

  useEffect(() => {
    const id = pending?.turn.turn_id;
    if (!id || !outcome || delivered.current.has(id)) return;
    delivered.current.add(id);
    handler.current(outcome);
  }, [pending?.turn.turn_id, outcome]);

  if (!pending) return null;
  const snapshot = turn.data ?? null;
  const runState = run.data ?? null;
  const progress: PlotRequestProgress = {
    kind: plotRun ? "figure" : "discussion",
    status: runState
      ? runState.status === "queued"
        ? "running"
        : runState.status
      : snapshot?.status === "completed"
        ? "running"
        : (snapshot?.status ?? "running"),
    error: null,
    prompt: pending.prompt,
    block_id: plotRun ? pending.versionId : null,
    assistant: pending.turn,
    assistant_state: snapshot,
    run: plotRun,
    run_state: runState,
  };
  async function refresh() {
    await turn.refetch();
    if (plotRun) await run.refetch();
  }
  async function cancel() {
    if (plotRun) await cancelPlotRun(plotRun.links.cancel);
    else if (pending?.turn.links.cancel)
      await cancelAssistant(pending.turn.links.cancel);
    await refresh();
  }
  return { progress, refresh, cancel };
}

function describeOutcome(
  turn: AssistantTurnSnapshot | undefined,
  run: PlotRunSnapshot | undefined,
  lost: boolean,
): RequestOutcome | null {
  if (lost)
    return {
      kind: "failed",
      text: "This request could not be followed. Check the plot list, then try again.",
    };
  if (!turn) return null;
  if (turn.status === "cancelled") return { kind: "cancelled" };
  if (turn.status === "failed")
    return {
      kind: "failed",
      text: turn.error?.message ?? "The request could not be completed.",
    };
  if (turn.status !== "completed" || !turn.response) return null;
  const response = turn.response;
  if (response.outcome === "message")
    return { kind: "reply", text: response.message ?? "" };
  if (!run) return null;
  if (run.status === "completed" && run.result)
    return {
      kind: "plot",
      result: run.result,
      text: response.intent.user_reply ?? null,
    };
  if (run.status === "cancelled") return { kind: "cancelled" };
  if (run.status === "failed")
    return {
      kind: "failed",
      text: run.failure?.message ?? "The plot could not be made.",
    };
  return null;
}

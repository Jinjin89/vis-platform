import { useEffect } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  getAssistantState,
  getPlotRun,
  startAssistantTurn,
  updatePlotParameters,
} from "../../api/client";
import { getPlotSource } from "../../api/plotSource";
import type { PlotNode } from "./model";
import { isActive } from "./model";

export type UpdatePlot = (id: string, update: Partial<PlotNode>) => void;
const terminal = new Set(["completed", "failed", "cancelled"]);

/** Each node tracks its own request. Switching selection never redirects a result. */
export function NodeExecution({
  node,
  projectId,
  onUpdate,
}: {
  node: PlotNode;
  projectId: string;
  onUpdate: UpdatePlot;
}) {
  const active = isActive(node);
  const submission = useQuery({
    queryKey: ["canvas-submit", projectId, node.request.id],
    queryFn: async () =>
      node.request.mode === "parameters"
        ? updatePlotParameters(
            projectId,
            node.request.plotId!,
            node.request.baseVersionId!,
            node.request.changes,
            node.request.id,
          )
        : startAssistantTurn(
            projectId,
            `${node.parentPlotId ? "Refine the selected plot" : "Create a plot from the selected dataset"}: ${node.prompt}`,
            node.request.baseVersionId,
            [node.sourceDatasetId],
            [],
            undefined,
            node.request.id,
            node.request.changes,
          ),
    enabled: active && !node.run && !node.assistant,
    staleTime: Infinity,
    retry: false,
  });
  useEffect(() => {
    const response = submission.data;
    if (!response || !active || node.run || node.assistant) return;
    if ("run_id" in response) onUpdate(node.id, { run: response });
    else if ("plot_run" in response && response.plot_run)
      onUpdate(node.id, { run: response.plot_run });
    else if (response.links.status)
      onUpdate(node.id, {
        assistant: {
          turnId: response.turn_id,
          status: response.links.status,
          cancel: response.links.cancel ?? null,
        },
      });
    else
      onUpdate(node.id, {
        status: "failed",
        error:
          "message" in response
            ? (response.message ?? "No plot was created.")
            : "The request could not be tracked.",
      });
  }, [
    submission.data,
    node.id,
    !!node.run,
    !!node.assistant,
    active,
    onUpdate,
  ]);
  useEffect(() => {
    if (active && !node.run && !node.assistant && submission.error)
      onUpdate(node.id, { status: "failed", error: submission.error.message });
  }, [
    submission.error,
    node.id,
    !!node.run,
    !!node.assistant,
    active,
    onUpdate,
  ]);

  const assistant = useQuery({
    queryKey: ["canvas-assistant", projectId, node.assistant?.turnId],
    queryFn: () => getAssistantState(node.assistant!.status),
    enabled: active && !!node.assistant && !node.run,
    refetchInterval: (query) =>
      query.state.error
        ? false
        : terminal.has(query.state.data?.status ?? "")
          ? false
          : 1000,
    retry: 3,
  });
  useEffect(() => {
    const state = assistant.data;
    if (!state || !active || node.run) return;
    if (state.response?.plot_run)
      onUpdate(node.id, {
        run: state.response.plot_run,
        assistantSnapshot: state,
        status: "running",
        error: null,
      });
    else if (terminal.has(state.status))
      onUpdate(node.id, {
        assistantSnapshot: state,
        status: state.status === "cancelled" ? "cancelled" : "failed",
        error:
          state.error?.message ??
          state.response?.message ??
          "The request completed without producing a plot. Refine your instructions and try again.",
      });
    else
      onUpdate(node.id, {
        assistantSnapshot: state,
        status:
          state.status === "awaiting_input" ? "awaiting_input" : "running",
        error: null,
      });
  }, [assistant.data, node.id, !!node.run, active, onUpdate]);
  useEffect(() => {
    if (assistant.error)
      onUpdate(node.id, {
        error: "Updates paused. " + assistant.error.message,
      });
  }, [assistant.error, node.id, onUpdate]);

  const run = useQuery({
    queryKey: ["canvas-run", projectId, node.run?.run_id],
    queryFn: () => getPlotRun(node.run!.links.status),
    enabled: active && !!node.run,
    refetchInterval: (query) =>
      query.state.error
        ? false
        : terminal.has(query.state.data?.status ?? "")
          ? false
          : 800,
    retry: 3,
  });
  useEffect(() => {
    const state = run.data;
    if (!state || !active) return;
    const status = state.status === "queued" ? "running" : state.status;
    if (state.status === "completed" && !state.result) {
      onUpdate(node.id, {
        snapshot: state,
        status: "failed",
        error:
          "This request produced analysis results without a plot. Create another branch with plotting instructions.",
      });
      return;
    }
    onUpdate(node.id, {
      snapshot: state,
      status,
      error: state.failure?.message ?? null,
      ...(state.result
        ? {
            title: state.result.title ?? state.result.preview.description,
            parameters: Object.fromEntries(
              (state.result.controls ?? []).map((c) => [c.id, c.value]),
            ),
          }
        : {}),
    });
  }, [run.data, node.id, active, onUpdate]);
  useEffect(() => {
    if (run.error)
      onUpdate(node.id, { error: "Updates paused. " + run.error.message });
  }, [run.error, node.id, onUpdate]);

  const result = node.snapshot?.result;
  const source = useQuery({
    queryKey: ["plot-source", projectId, result?.version_id],
    queryFn: () =>
      getPlotSource(projectId, result!.plot_id, result!.version_id),
    enabled: node.status === "completed" && !!result && !node.source,
    staleTime: Infinity,
  });
  useEffect(() => {
    if (source.data) onUpdate(node.id, { source: source.data });
  }, [source.data, node.id, onUpdate]);
  return null;
}

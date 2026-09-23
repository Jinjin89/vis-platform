import { useCallback, useEffect, useRef, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useSearchParams } from "react-router";
import { createMutationId, resolveArtifactUrl } from "../api/client";
import { sendPinpointRequest, type PlotMark } from "../api/pinpoint";
import { listReportFigures } from "../api/reports";
import type { PlotResult } from "../api/schemas/plotRun";
import { useProject } from "../app/useProject";
import { SessionSidebar } from "../components/SessionSidebar";
import { WorkspaceSwitcher } from "../components/WorkspaceSwitcher";
import { PinpointConversation } from "../features/pinpoint/PinpointConversation";
import { PinpointStage } from "../features/pinpoint/PinpointStage";
import { PointMapStage } from "../features/pinpoint/PointMapStage";
import { isImageMark } from "../features/pinpoint/marks";
import {
  NEW_PLOT,
  readConversation,
  writeConversation,
  type PinpointMessage,
} from "../features/pinpoint/pinpointHistory";
import {
  usePinpointRequest,
  type RequestOutcome,
} from "../features/pinpoint/usePinpointRequest";
import { ReportEditStatus } from "../features/reports/ReportEditStatus";
import "../features/pinpoint/pinpoint.css";

export function PinpointPage() {
  const project = useProject(true);
  return (
    <main className="app-shell pinpoint-shell">
      <header className="top-bar">
        <div className="brand" aria-label="Vis Platform">
          <span className="brand-name">vis.</span>
        </div>
        <div className="project-title">
          <span className="project-kicker">Research studio</span>
          <strong>Pinpoint</strong>
        </div>
        <WorkspaceSwitcher />
      </header>
      {project.projectId ? (
        <PinpointPlots key={project.projectId} projectId={project.projectId} />
      ) : (
        <div className="pinpoint-loading">
          {project.error ? (
            <>
              <p role="alert">{project.error}</p>
              <button type="button" onClick={project.retry}>
                Retry opening your study
              </button>
            </>
          ) : (
            <p>Opening your study…</p>
          )}
        </div>
      )}
    </main>
  );
}

/** Every plot in the study, each with its own conversation. */
function PinpointPlots({ projectId }: { projectId: string }) {
  const [params, setParams] = useSearchParams();
  const queryClient = useQueryClient();
  const plots = useQuery({
    queryKey: ["pinpoint-plots", projectId],
    queryFn: () => listReportFigures(projectId),
  });
  const figures = plots.data?.figures ?? [];
  const selected =
    params.get("new") === "1"
      ? null
      : (figures.find((figure) => figure.plot_id === params.get("plot")) ??
        figures[0] ??
        null);
  const opened = useCallback(
    (result: PlotResult) => {
      // Show the new version at once; the list then refreshes from the backend.
      queryClient.setQueryData<typeof plots.data>(
        ["pinpoint-plots", projectId],
        (current) =>
          current && {
            ...current,
            figures: [
              result,
              ...current.figures.filter(
                (figure) => figure.plot_id !== result.plot_id,
              ),
            ],
          },
      );
      void plots.refetch();
      setParams({ plot: result.plot_id });
    },
    [queryClient, projectId, plots.refetch, setParams],
  );
  return (
    <div className="session-layout">
      <SessionSidebar
        label="Plots"
        newLabel="New plot"
        items={figures.map((figure) => ({
          id: figure.plot_id,
          title: figure.title || "Untitled plot",
          detail:
            figure.execution_mode === "demo"
              ? "Demonstration data"
              : "Your data",
        }))}
        activeId={selected?.plot_id ?? null}
        loading={plots.isPending}
        error={plots.error ? "The plots could not be loaded." : null}
        emptyText="Plots you make here or in any other interface appear here."
        onSelect={(id) => setParams({ plot: id })}
        onNew={() => setParams({ new: "1" })}
        onRetry={() => void plots.refetch()}
      />
      {plots.isPending ? (
        <div className="pinpoint-loading">
          <p>Loading your plots…</p>
        </div>
      ) : (
        <PinpointWorkspace
          key={selected?.plot_id ?? NEW_PLOT}
          projectId={projectId}
          plot={selected}
          onPlot={opened}
        />
      )}
    </div>
  );
}

function PinpointWorkspace({
  projectId,
  plot,
  onPlot,
}: {
  projectId: string;
  plot: PlotResult | null;
  onPlot: (result: PlotResult) => void;
}) {
  const conversationId = plot?.plot_id ?? NEW_PLOT;
  const [conversation, setConversation] = useState(() =>
    readConversation(projectId, conversationId),
  );
  const latest = useRef(conversation);
  latest.current = conversation;
  const [marks, setMarks] = useState<PlotMark[]>([]);
  const [staticView, setStaticView] = useState<string | null>(null);
  const addMark = (mark: PlotMark) => setMarks((current) => [...current, mark]);
  const removeMark = (number: number) =>
    setMarks((current) => current.filter((mark) => mark.number !== number));
  const [draft, setDraft] = useState("");
  const [sending, setSending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const versionId = plot?.version_id ?? null;
  useEffect(
    () => writeConversation(projectId, conversationId, conversation),
    [projectId, conversationId, conversation],
  );
  // Marks are places on one version's image.
  useEffect(() => setMarks([]), [versionId]);

  const finish = useCallback(
    (outcome: RequestOutcome) => {
      const next = {
        pending: null,
        messages: [...latest.current.messages, replyTo(outcome)],
      };
      if (outcome.kind === "plot" && conversationId === NEW_PLOT) {
        // The conversation moves to the plot it made; New plot starts empty again.
        writeConversation(projectId, outcome.result.plot_id, next);
        setConversation({ pending: null, messages: [] });
      } else setConversation(next);
      if (outcome.kind === "plot") onPlot(outcome.result);
    },
    [projectId, conversationId, onPlot],
  );
  const request = usePinpointRequest(conversation.pending, finish);
  const busy = sending || Boolean(conversation.pending);

  async function send(text: string) {
    setSending(true);
    setError(null);
    try {
      const turn = await sendPinpointRequest(projectId, {
        text,
        baseVersionId: versionId,
        marks,
        requestId: createMutationId(),
      });
      setConversation((current) => ({
        messages: [
          ...current.messages,
          {
            id: turn.turn_id,
            role: "user",
            text,
            ...(marks.length ? { marks, versionId } : {}),
          },
        ],
        pending: { turn, prompt: text, versionId },
      }));
      setDraft("");
    } catch (reason) {
      setError(
        reason instanceof Error
          ? reason.message
          : "The request could not be sent.",
      );
    } finally {
      setSending(false);
    }
  }

  return (
    <div className="pinpoint-workspace">
      <section className="pinpoint-canvas" aria-label="Plot">
        {plot ? (
          <>
            <header className="pinpoint-canvas-head">
              <h1>{plot.title || "Untitled plot"}</h1>
              {plot.execution_mode === "demo" ? (
                <span className="pinpoint-note">
                  Demonstration plot: marks are shown on the image only.
                </span>
              ) : null}
            </header>
            {plot.interactive_view === "points" && !staticView ? (
              <PointMapStage
                projectId={projectId}
                plotId={plot.plot_id}
                versionId={plot.version_id}
                marks={marks}
                disabled={busy}
                onMark={addMark}
                onRemove={removeMark}
                onUnavailable={(reason) => {
                  // Marks from the interactive view mean nothing on the image.
                  setMarks([]);
                  setStaticView(reason);
                }}
              />
            ) : (
              <>
                {staticView ? (
                  <p className="pinpoint-note" role="status">
                    The interactive view is unavailable in this browser (
                    {staticView}), so the saved figure is shown.
                  </p>
                ) : null}
                <PinpointStage
                  src={resolveArtifactUrl(plot.preview.href)}
                  alt={plot.preview.description}
                  marks={marks.filter(isImageMark)}
                  disabled={busy}
                  onMark={addMark}
                  onRemove={removeMark}
                />
              </>
            )}
          </>
        ) : (
          <div className="pinpoint-empty-stage">
            <strong>New plot</strong>
            <p>
              Describe what you want to see. The plot appears here, ready to
              mark and discuss.
            </p>
          </div>
        )}
      </section>
      <PinpointConversation
        messages={conversation.messages}
        marks={marks}
        busy={busy}
        canMark={Boolean(plot)}
        draft={draft}
        onDraft={setDraft}
        onRemoveMark={removeMark}
        onClearMarks={() => setMarks([])}
        onSend={(text) => void send(text)}
        status={
          <>
            {request ? (
              <ReportEditStatus
                edit={request.progress}
                projectId={projectId}
                refresh={request.refresh}
                onCancel={request.cancel}
                onRetry={() => undefined}
                showPrompt={false}
              />
            ) : null}
            {error ? (
              <p role="alert" className="pinpoint-error">
                {error}
              </p>
            ) : null}
          </>
        }
      />
    </div>
  );
}

function replyTo(outcome: RequestOutcome): PinpointMessage {
  const id = createMutationId();
  if (outcome.kind === "reply")
    return { id, role: "assistant", text: outcome.text };
  if (outcome.kind === "plot")
    return {
      id,
      role: "assistant",
      text: outcome.text || "Here is the updated plot.",
    };
  if (outcome.kind === "cancelled")
    return { id, role: "assistant", text: "Request cancelled." };
  return { id, role: "assistant", text: outcome.text, tone: "error" };
}

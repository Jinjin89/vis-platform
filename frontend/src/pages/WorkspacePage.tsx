import { DatasetSelector } from "../features/datasets/DatasetSelector";
import {
  uploadReferenceImage,
  deleteReferenceImage,
} from "../api/referenceImages";
import type { ReferenceImage } from "../api/schemas/referenceImages";
import type { AnalysisResult } from "../api/schemas/datasets";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";
import { useSearchParams } from "react-router";

import {
  ApiClientError,
  answerQuestion,
  cancelPlotRun,
  startAssistantTurn,
  createMutationId,
  createRunEventSource,
  decideApproval,
  getPlotRun,
  updatePlotParameters,
  restorePlotVersion,
  type QuestionAnswer,
} from "../api/client";
import {
  apiPathSchema,
  type AssistantTurnResponse,
  type ArtifactReference,
  type ParameterValues,
  type PlotRunAccepted,
  type PlotRunSnapshot,
  runEventSchema,
} from "../api/schemas/plotRun";
import type { WorkspaceSessionDocument } from "../api/schemas/workspaceSessions";
import {
  createWorkspaceSession,
  getWorkspaceSession,
  listWorkspaceSessions,
} from "../api/workspaceSessions";
import { useProject } from "../app/useProject";
import { ResizablePanels } from "../components/ResizablePanels";
import { LogoMark } from "../components/Icons";
import { SessionSidebar, editedOn } from "../components/SessionSidebar";
import { WorkspaceSwitcher } from "../components/WorkspaceSwitcher";
import { ConversationPanel } from "../features/plot-run/ConversationPanel";
import {
  answeredQuestions,
  restoreConversation,
  runMessage,
} from "../features/plot-run/conversationHistory";
import { PlotCanvas } from "../features/plot-run/PlotCanvas";
import { useAssistantPlanner } from "../features/plot-run/useAssistantPlanner";
import type { PlannerAnswer } from "../api/schemas/planner";
import type {
  ConversationMessage,
  DeveloperTraceTarget,
} from "../features/plot-run/types";

const EVENT_TYPES = [
  "run.started",
  "progress.updated",
  "question.required",
  "approval.required",
  "preview.ready",
  "run.completed",
  "run.failed",
  "run.cancelled",
] as const;

const TERMINAL_STATUSES = new Set(["completed", "failed", "cancelled"]);
const MAX_POLL_FAILURES = 5;

const NEW_CONVERSATION = "new";

/**
 * Conversations are listed beside the workspace and saved as they happen. Opening the
 * Workspace continues the latest one.
 */
export function WorkspacePage() {
  const project = useProject(false);
  const projectId = project.projectId;
  const queryClient = useQueryClient();
  const [params, setParams] = useSearchParams();
  const requested = params.get("session");
  const [offset, setOffset] = useState(0);
  const sessions = useQuery({
    queryKey: ["workspace-sessions", projectId, offset],
    queryFn: () => listWorkspaceSessions(projectId!, offset),
    enabled: !!projectId,
  });
  // Only opening the page continues the latest conversation; a study created later does not.
  const [landing, setLanding] = useState(requested === null);
  const latest = sessions.data?.sessions[0]?.session_id;
  useEffect(() => {
    if (!landing || project.opening) return;
    if (requested !== null) setLanding(false);
    else if (latest) setParams({ session: latest }, { replace: true });
    else if (!projectId || !sessions.isPending) setLanding(false);
  }, [
    landing,
    requested,
    latest,
    project.opening,
    projectId,
    sessions.isPending,
  ]);
  const sessionId =
    requested && requested !== NEW_CONVERSATION ? requested : null;
  // A new conversation gets its ID with its first message and stays on screen as it is.
  // Only the mounted conversation that saved itself is kept; later visits reopen it.
  const created = useRef<{ key: number; sessionId: string } | null>(null);
  const [mount, setMount] = useState({
    key: 0,
    sessionId,
    restore: sessionId !== null,
  });
  if (mount.sessionId !== sessionId)
    setMount(
      mount.sessionId === null &&
        created.current?.key === mount.key &&
        created.current.sessionId === sessionId
        ? { ...mount, sessionId }
        : { key: mount.key + 1, sessionId, restore: sessionId !== null },
    );
  const opened = useQuery({
    queryKey: ["workspace-session", projectId, mount.sessionId, mount.key],
    queryFn: () => getWorkspaceSession(projectId!, mount.sessionId!),
    enabled: mount.restore && !!projectId,
    gcTime: 0,
    staleTime: Infinity,
    retry: false,
  });
  const opening =
    project.opening ||
    (landing && !!projectId && (sessions.isPending || latest !== undefined)) ||
    (mount.restore && !!projectId && opened.isPending);
  const unavailable = opened.isError
    ? opened.error.message
    : mount.restore && !projectId && !project.opening
      ? "This conversation belongs to a study that is not open in this browser."
      : null;
  // A first message may start the study too, so every conversation list is refreshed.
  const refreshList = () =>
    void queryClient.invalidateQueries({ queryKey: ["workspace-sessions"] });
  return (
    <main className="app-shell">
      <header className="top-bar">
        <div className="brand" aria-label="Vis Platform">
          <span className="brand-mark">
            <LogoMark />
          </span>
          <span className="brand-name">vis.</span>
        </div>
        <div className="project-title">
          <span className="project-kicker">Research studio</span>
          <strong>Untitled study</strong>
        </div>
        <WorkspaceSwitcher />
      </header>
      <div className="session-layout">
        <SessionSidebar
          label="Conversations"
          newLabel="New conversation"
          // The figure, its controls, and the conversation need the width of a large screen.
          openFrom={1600}
          items={(sessions.data?.sessions ?? []).map((session) => ({
            id: session.session_id,
            title: session.title,
            detail: editedOn(session.updated_at),
          }))}
          activeId={sessionId}
          loading={!!projectId && sessions.isPending}
          error={sessions.error?.message}
          emptyText="Your conversations will appear here."
          onSelect={(id) => setParams({ session: id })}
          onNew={() => setParams({ session: NEW_CONVERSATION })}
          onRetry={() => void sessions.refetch()}
          footer={
            (sessions.data?.total ?? 0) > 30 ? (
              <div className="session-sidebar-pages">
                <button
                  type="button"
                  disabled={!offset}
                  onClick={() => setOffset(offset - 30)}
                >
                  Newer
                </button>
                <button
                  type="button"
                  disabled={offset + 30 >= (sessions.data?.total ?? 0)}
                  onClick={() => setOffset(offset + 30)}
                >
                  Older
                </button>
              </div>
            ) : null
          }
        />
        {project.error ? (
          <div className="workspace-opening" role="alert">
            <p>{project.error}</p>
            <button type="button" onClick={project.retry}>
              Retry
            </button>
          </div>
        ) : unavailable ? (
          <div className="workspace-opening" role="alert">
            <p>{unavailable}</p>
            <button
              type="button"
              onClick={() => setParams({ session: NEW_CONVERSATION })}
            >
              Start a new conversation
            </button>
          </div>
        ) : opening ? (
          <div className="workspace-opening" role="status">
            <p>Opening your conversation…</p>
          </div>
        ) : (
          <WorkspaceConversation
            key={mount.key}
            projectId={projectId}
            ensureProject={project.ensure}
            session={mount.restore ? (opened.data ?? null) : null}
            onSessionCreated={(id) => {
              created.current = { key: mount.key, sessionId: id };
              setParams({ session: id }, { replace: true });
            }}
            onActivity={refreshList}
          />
        )}
      </div>
    </main>
  );
}

function WorkspaceConversation({
  projectId,
  ensureProject,
  session,
  onSessionCreated,
  onActivity,
}: {
  projectId: string | null;
  ensureProject: () => Promise<string>;
  session: WorkspaceSessionDocument | null;
  onSessionCreated: (sessionId: string) => void;
  onActivity: () => void;
}) {
  const [restored] = useState(() =>
    session ? restoreConversation(session) : null,
  );
  const [selectedDatasetIds, setSelectedDatasetIds] = useState<string[]>(() =>
    readSessionIds("vis-platform.selected-datasets"),
  );
  const [selectedResultIds, setSelectedResultIds] = useState<string[]>(() =>
    readSessionIds("vis-platform.selected-results"),
  );
  const [draftRequest, setDraftRequest] = useState<{
    text: string;
    key: number;
  }>();
  const conversation = useRef({
    sessionId: session?.session_id ?? null,
    request: { title: "", key: createMutationId() },
  });
  const live = useRef(true);
  const submissionBusy = useRef(false);
  const lastSubmission = useRef<{ fingerprint: string; key: string } | null>(
    null,
  );
  const queryClient = useQueryClient();
  useEffect(() => {
    try {
      window.sessionStorage.setItem(
        "vis-platform.selected-datasets",
        JSON.stringify(selectedDatasetIds),
      );
      window.sessionStorage.setItem(
        "vis-platform.selected-results",
        JSON.stringify(selectedResultIds),
      );
    } catch {
      /* The workspace also works when browser storage is disabled. */
    }
  }, [selectedDatasetIds, selectedResultIds]);
  /** The conversation is saved with its first message. */
  async function ensureSession(activeProjectId: string, text: string) {
    const current = conversation.current;
    if (current.sessionId) return current.sessionId;
    const title = conversationTitle(text);
    // A retry of the same first message must not start a second conversation.
    if (current.request.title !== title)
      current.request = { title, key: createMutationId() };
    const created = await createWorkspaceSession(
      activeProjectId,
      title,
      current.request.key,
    );
    current.sessionId = created.session_id;
    if (live.current) onSessionCreated(created.session_id);
    return created.session_id;
  }
  function useAnalysisResult(result: AnalysisResult) {
    setSelectedDatasetIds([]);
    setSelectedResultIds([result.result_id]);
    setDraftRequest({
      key: Date.now(),
      text: `Create a figure using the saved analysis “${result.name}”.`,
    });
    setWorkspaceView("conversation");
  }
  const [committedSnapshot, setCommittedSnapshot] =
    useState<PlotRunSnapshot | null>(restored?.figure ?? null);
  const [activeSnapshot, setActiveSnapshot] = useState<PlotRunSnapshot | null>(
    null,
  );
  const [activeRun, setActiveRun] = useState<PlotRunAccepted | null>(null);
  const [provisionalPreview, setProvisionalPreview] =
    useState<ArtifactReference | null>(null);
  const [messages, setMessages] = useState<ConversationMessage[]>(
    restored?.messages ?? [],
  );
  const [traceTargets, setTraceTargets] = useState<DeveloperTraceTarget[]>(
    restored?.traceTargets ?? [],
  );
  const [figureBrief, setFigureBrief] = useState<string | undefined>(
    restored?.figure?.result?.title ?? undefined,
  );
  const [progressMessage, setProgressMessage] = useState("Ready to begin");
  const [progressValue, setProgressValue] = useState(0);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [interactionBusy, setInteractionBusy] = useState(false);
  const [interactionError, setInteractionError] = useState<string | null>(null);
  const [isCancelling, setIsCancelling] = useState(false);
  const [plotMutationPending, setPlotMutationPending] = useState(false);
  const plotMutationBusy = useRef(false);
  const eventSource = useRef<EventSource | null>(null);
  const pollTimer = useRef<number | null>(null);
  const messageSequence = useRef(restored?.messages.length ?? 0);
  const finalizedRuns = useRef(new Set<string>());
  const recordedInteractions = useRef(new Set(restored?.interactions));
  const runTurns = useRef(new Map<string, string>());
  const [workspaceView, setWorkspaceView] = useState<"figure" | "conversation">(
    "conversation",
  );

  useEffect(() => {
    live.current = true;
    // A reopened conversation reconnects to the request or run it left unfinished.
    if (restored?.pendingTurn && projectId)
      planner.track(
        restored.pendingTurn.accepted,
        projectId,
        restored.pendingTurn.text,
      );
    if (restored?.pendingRun) {
      runTurns.current.set(
        restored.pendingRun.accepted.run_id,
        restored.pendingRun.turnId,
      );
      startListening(restored.pendingRun.accepted);
    }
    return () => {
      live.current = false;
      stopListening();
    };
  }, []);

  const turnMutation = useMutation({
    mutationFn: async ({
      text,
      images,
    }: {
      text: string;
      images: ReferenceImage[];
    }) => {
      const activeProjectId = await ensureProject();
      const sessionId = await ensureSession(activeProjectId, text);
      const fingerprint = JSON.stringify({
        activeProjectId,
        sessionId,
        text,
        images: images.map((image) => image.image_id),
        baseVersion: committedSnapshot?.result?.version_id,
        selectedDatasetIds,
        selectedResultIds,
      });
      if (lastSubmission.current?.fingerprint !== fingerprint)
        lastSubmission.current = {
          fingerprint,
          key:
            globalThis.crypto?.randomUUID?.() ??
            `turn-${Date.now()}-${Math.random().toString(36).slice(2)}`,
        };
      const submission = await startAssistantTurn(
        activeProjectId,
        text,
        committedSnapshot?.result?.version_id,
        selectedDatasetIds,
        selectedResultIds,
        images.length ? images.map((image) => image.image_id) : undefined,
        lastSubmission.current.key,
        undefined,
        sessionId,
      );
      lastSubmission.current = null;
      onActivity();
      return { submission, projectId: activeProjectId };
    },
  });

  const planner = useAssistantPlanner(
    {
      onResponse: handleTurnResponse,
      onCancelled: (turnId) => {
        appendMessage(
          "assistant",
          "I stopped this request. Your saved figure is unchanged.",
          "default",
          turnId,
        );
        setErrorMessage(null);
        setProgressValue(0);
      },
      onError: (message, turnId) => {
        appendMessage("assistant", message, "error", turnId);
        setErrorMessage(message);
        setProgressValue(0);
      },
      onReferences: (turnId, images) => {
        setMessages((current) =>
          current.map((message) =>
            message.role === "user" && message.turnId === turnId
              ? { ...message, referenceImages: images }
              : message,
          ),
        );
      },
    },
    restored?.activities,
  );
  useEffect(() => {
    if (planner.pendingQuestion) setWorkspaceView("conversation");
  }, [planner.pendingQuestion?.question.interaction_id]);

  function handleTurnResponse(turn: AssistantTurnResponse, text: string) {
    appendTraceTarget({
      turnId: turn.turn_id,
      traceHref: turn.links.trace,
      request: text,
    });
    if (turn.outcome === "message") {
      appendMessage("assistant", turn.message ?? "", "default", turn.turn_id);
      setProgressMessage("Ready for your next idea");
      setProgressValue(0);
      return;
    }
    if (turn.outcome === "plot_run" && turn.plot_run) {
      runTurns.current.set(turn.plot_run.run_id, turn.turn_id);
      if (turn.intent.kind === "plot_create")
        setFigureBrief(turn.intent.normalized_request);
      startListening(turn.plot_run);
    }
  }

  async function handlePlannerAnswer(
    answers: PlannerAnswer[],
  ): Promise<boolean> {
    const pending = planner.pendingQuestion;
    if (!pending) return false;
    const accepted = await planner.answer(answers);
    if (accepted) {
      const exchange = answeredQuestions(pending.question, answers);
      recordInteraction(
        pending.question.interaction_id,
        exchange.prompt,
        exchange.answer,
      );
    }
    return accepted;
  }

  function stopListening() {
    eventSource.current?.close();
    eventSource.current = null;
    if (pollTimer.current !== null) {
      window.clearTimeout(pollTimer.current);
      pollTimer.current = null;
    }
  }

  function appendMessage(
    role: ConversationMessage["role"],
    content: string,
    tone: ConversationMessage["tone"] = "default",
    turnId?: string,
    analysisResults?: AnalysisResult[],
    referenceImages?: ReferenceImage[],
  ) {
    messageSequence.current += 1;
    const message: ConversationMessage = {
      id: `message_${messageSequence.current}`,
      role,
      content,
      tone,
      turnId,
      analysisResults,
      referenceImages,
    };
    setMessages((current) => [...current, message]);
  }

  function appendTraceTarget(target: DeveloperTraceTarget) {
    setTraceTargets((current) =>
      current.some((candidate) => candidate.turnId === target.turnId)
        ? current
        : [...current, target],
    );
  }

  function recordInteraction(
    interactionKey: string,
    assistantMessage: string,
    userMessage: string,
  ) {
    if (recordedInteractions.current.has(interactionKey)) {
      return;
    }
    recordedInteractions.current.add(interactionKey);
    appendMessage("assistant", assistantMessage);
    appendMessage("user", userMessage);
  }

  async function submitRequest(
    text: string,
    images: ReferenceImage[] = [],
  ): Promise<boolean> {
    if (
      submissionBusy.current ||
      planner.working ||
      planner.pendingQuestion ||
      plotMutationBusy.current
    )
      return false;
    submissionBusy.current = true;
    setWorkspaceView("conversation");
    setErrorMessage(null);
    setInteractionError(null);
    setActiveSnapshot(null);
    setProgressMessage("Understanding your request");
    setProgressValue(6);
    try {
      const result = await turnMutation.mutateAsync({ text, images });
      appendMessage(
        "user",
        text,
        "default",
        result.submission.turn_id,
        undefined,
        images,
      );
      planner.track(result.submission, result.projectId, text);
      return true;
    } catch (error) {
      const traceTarget = traceTargetFromError(error, text);
      if (traceTarget != null) {
        appendTraceTarget(traceTarget);
      }
      const message = messageForError(error);
      appendMessage("assistant", message, "error");
      setErrorMessage(message);
      setProgressValue(0);
      return false;
    } finally {
      submissionBusy.current = false;
    }
  }

  async function applyParameters(
    changes: ParameterValues,
    requestId: string,
  ): Promise<boolean> {
    const snapshot = committedSnapshot;
    if (
      snapshot?.result == null ||
      plotMutationBusy.current ||
      activeRun != null ||
      turnMutation.isPending
    )
      return false;
    plotMutationBusy.current = true;
    setPlotMutationPending(true);
    try {
      const accepted = await updatePlotParameters(
        snapshot.project_id,
        snapshot.result.plot_id,
        snapshot.result.version_id,
        changes,
        requestId,
      );
      appendMessage("user", "Apply figure parameter changes");
      startListening(accepted);
      return true;
    } finally {
      plotMutationBusy.current = false;
      setPlotMutationPending(false);
    }
  }

  async function selectVersion(runId: string): Promise<void> {
    if (activeRun != null || plotMutationBusy.current || turnMutation.isPending)
      return;
    const snapshot = await getPlotRun(
      `/api/v1/plot-runs/${encodeURIComponent(runId)}`,
    );
    if (
      snapshot.status !== "completed" ||
      snapshot.result == null ||
      snapshot.project_id !== committedSnapshot?.project_id ||
      snapshot.result.plot_id !== committedSnapshot.result?.plot_id
    )
      throw new Error("The version does not belong to this figure.");
    setCommittedSnapshot(snapshot);
    setFigureBrief(snapshot.result.title ?? undefined);
    setErrorMessage(null);
  }

  async function restoreVersion(
    versionId: string,
    requestId: string,
  ): Promise<boolean> {
    const snapshot = committedSnapshot;
    if (
      snapshot?.result == null ||
      plotMutationBusy.current ||
      activeRun != null ||
      turnMutation.isPending
    )
      return false;
    plotMutationBusy.current = true;
    setPlotMutationPending(true);
    try {
      const accepted = await restorePlotVersion(
        snapshot.project_id,
        snapshot.result.plot_id,
        versionId,
        requestId,
      );
      appendMessage("user", "Restore an earlier figure version");
      startListening(accepted);
      return true;
    } finally {
      plotMutationBusy.current = false;
      setPlotMutationPending(false);
    }
  }

  function startListening(accepted: PlotRunAccepted) {
    stopListening();
    setActiveRun(accepted);
    setActiveSnapshot(null);
    setProvisionalPreview(null);
    setProgressMessage("Preparing the figure workspace");
    setProgressValue(10);
    setErrorMessage(null);
    setInteractionError(null);
    if (TERMINAL_STATUSES.has(accepted.status)) {
      void getPlotRun(accepted.links.status)
        .then(finishRun)
        .catch((error) => recoverFromRunError(accepted, error));
      return;
    }

    const source = createRunEventSource(accepted.links.events);
    eventSource.current = source;
    for (const eventType of EVENT_TYPES) {
      source.addEventListener(eventType, (message) => {
        void handleRunEvent(accepted, message as MessageEvent<string>).catch(
          (error: unknown) => recoverFromRunError(accepted, error),
        );
      });
    }
    source.onerror = () => {
      source.close();
      if (eventSource.current === source) {
        eventSource.current = null;
      }
      setProgressMessage("Reconnecting to the figure run");
      schedulePoll(accepted, 0, 300);
    };
  }

  async function handleRunEvent(
    accepted: PlotRunAccepted,
    message: MessageEvent<string>,
  ) {
    let body: unknown;
    try {
      body = JSON.parse(message.data);
    } catch {
      recoverFromInvalidEvent(accepted);
      return;
    }
    const parsed = runEventSchema.safeParse(body);
    if (!parsed.success) {
      recoverFromInvalidEvent(accepted);
      return;
    }
    const event = parsed.data;

    if (event.type === "progress.updated") {
      setProgressMessage(event.payload.message);
      setProgressValue(event.payload.progress);
    } else if (event.type === "preview.ready") {
      setProvisionalPreview(event.payload.artifact);
      setProgressValue(96);
    } else if (
      event.type === "question.required" ||
      event.type === "approval.required"
    ) {
      await refreshActiveSnapshot(accepted);
    } else if (
      event.type === "run.completed" ||
      event.type === "run.failed" ||
      event.type === "run.cancelled"
    ) {
      eventSource.current?.close();
      eventSource.current = null;
      setProgressMessage("Finishing the figure");
      setProgressValue(98);
      try {
        await finishRun(await getPlotRun(accepted.links.status));
      } catch {
        schedulePoll(accepted, 0, 250);
      }
    }
  }

  function recoverFromInvalidEvent(accepted: PlotRunAccepted) {
    eventSource.current?.close();
    eventSource.current = null;
    setProgressMessage("Reconnecting after an invalid progress update");
    schedulePoll(accepted, 0, 300);
  }

  function recoverFromRunError(accepted: PlotRunAccepted, error: unknown) {
    eventSource.current?.close();
    eventSource.current = null;
    setErrorMessage(messageForError(error));
    schedulePoll(accepted, 0, 300);
  }

  async function refreshActiveSnapshot(accepted: PlotRunAccepted) {
    try {
      const snapshot = await getPlotRun(accepted.links.status);
      setActiveSnapshot(snapshot);
      if (snapshot.progress != null) {
        setProgressMessage(snapshot.progress.message);
        setProgressValue(snapshot.progress.progress);
      }
      setInteractionError(null);
    } catch (error) {
      setInteractionError(messageForError(error));
      setProgressMessage("Reconnecting to the question or decision");
      schedulePoll(accepted, 0, 300);
    }
  }

  function schedulePoll(
    accepted: PlotRunAccepted,
    failureCount = 0,
    delay = 650,
  ) {
    if (pollTimer.current !== null) {
      window.clearTimeout(pollTimer.current);
    }
    pollTimer.current = window.setTimeout(async () => {
      pollTimer.current = null;
      try {
        const snapshot = await getPlotRun(accepted.links.status);
        setActiveSnapshot(snapshot);
        setErrorMessage(null);
        setInteractionError(null);
        if (snapshot.progress != null) {
          setProgressMessage(snapshot.progress.message);
          setProgressValue(snapshot.progress.progress);
        }
        if (TERMINAL_STATUSES.has(snapshot.status)) {
          await finishRun(snapshot);
        } else if (
          snapshot.status !== "awaiting_input" &&
          snapshot.status !== "awaiting_approval"
        ) {
          schedulePoll(accepted);
        }
      } catch (error) {
        if (failureCount < MAX_POLL_FAILURES) {
          setProgressMessage("Connection interrupted — retrying safely");
          const nextDelay = Math.min(600 * 2 ** failureCount, 4_800);
          schedulePoll(accepted, failureCount + 1, nextDelay);
          return;
        }
        setActiveRun(null);
        setProgressValue(0);
        const message = messageForError(error);
        appendMessage(
          "assistant",
          `I lost the connection to this run. Your last saved figure is still safe. ${message}`,
          "error",
        );
        setErrorMessage(message);
      }
    }, delay);
  }

  async function finishRun(snapshot: PlotRunSnapshot) {
    if (finalizedRuns.current.has(snapshot.run_id)) {
      return;
    }
    finalizedRuns.current.add(snapshot.run_id);
    stopListening();
    setActiveSnapshot(snapshot);
    setActiveRun(null);
    setProvisionalPreview(null);
    setProgressValue(100);
    if (projectId)
      void queryClient.invalidateQueries({
        queryKey: ["analysis-results", projectId],
      });

    const message = runMessage(snapshot);
    if (message)
      appendMessage(
        "assistant",
        message.content,
        message.tone,
        runTurns.current.get(snapshot.run_id),
        message.analysisResults,
      );
    if (snapshot.status === "completed" && snapshot.result != null) {
      setCommittedSnapshot(snapshot);
      setWorkspaceView("figure");
      if (snapshot.result.title != null) setFigureBrief(snapshot.result.title);
      setErrorMessage(null);
      setProgressMessage(
        snapshot.result.execution_mode === "demo"
          ? "Demonstration figure ready"
          : "Figure checked and saved",
      );
    } else if (
      snapshot.status === "completed" &&
      snapshot.analysis_results?.length
    ) {
      setErrorMessage(null);
      setProgressMessage("Analysis saved");
    } else if (snapshot.status === "failed") {
      setErrorMessage(snapshot.failure?.message ?? "The figure run failed.");
      setProgressValue(0);
    } else if (snapshot.status === "cancelled") {
      setProgressMessage("Run stopped");
      setProgressValue(0);
    }
  }

  async function handleQuestionAnswer(
    questionId: string,
    answer: QuestionAnswer,
  ) {
    if (activeRun === null || interactionBusy) {
      return;
    }
    const run = activeRun;
    const question = activeSnapshot?.pending_question;
    setInteractionBusy(true);
    setInteractionError(null);
    try {
      const resumed = await answerQuestion(run.run_id, questionId, answer);
      if (question?.question_id === questionId) {
        const answerLabel =
          answer.choiceId == null
            ? answer.freeText
            : question.choices.find(
                (choice) => choice.choice_id === answer.choiceId,
              )?.label;
        if (answerLabel != null && answerLabel.length > 0) {
          recordInteraction(
            `${run.run_id}:question:${questionId}`,
            question.prompt,
            answerLabel,
          );
        }
      }
      startListening(resumed);
    } catch (error) {
      setInteractionError(messageForError(error));
    } finally {
      setInteractionBusy(false);
    }
  }

  async function handleApprovalDecision(
    approvalId: string,
    decision: "approve" | "reject",
  ) {
    if (activeRun === null || interactionBusy) {
      return;
    }
    const run = activeRun;
    const approval = activeSnapshot?.pending_approval;
    setInteractionBusy(true);
    setInteractionError(null);
    try {
      const resumed = await decideApproval(run.run_id, approvalId, decision);
      if (approval?.approval_id === approvalId) {
        recordInteraction(
          `${run.run_id}:approval:${approvalId}`,
          approval.summary,
          decision === "approve" ? "Approve change" : "Keep data unchanged",
        );
      }
      startListening(resumed);
    } catch (error) {
      setInteractionError(messageForError(error));
    } finally {
      setInteractionBusy(false);
    }
  }

  async function handleCancel() {
    if (activeRun === null) {
      await planner.cancel();
      return;
    }
    if (isCancelling) return;
    setIsCancelling(true);
    setInteractionError(null);
    try {
      stopListening();
      await finishRun(await cancelPlotRun(activeRun.links.cancel));
    } catch (error) {
      setErrorMessage(messageForError(error));
      schedulePoll(activeRun, 0, 300);
    } finally {
      setIsCancelling(false);
    }
  }

  const waitingForInteraction =
    Boolean(planner.pendingQuestion) ||
    activeSnapshot?.status === "awaiting_input" ||
    activeSnapshot?.status === "awaiting_approval";
  const isRunning =
    planner.working ||
    plotMutationPending ||
    turnMutation.isPending ||
    (activeRun !== null && !waitingForInteraction);
  const statusMessage =
    errorMessage != null
      ? "Needs attention"
      : waitingForInteraction
        ? "Your input is needed"
        : isRunning
          ? progressMessage
          : committedSnapshot?.result != null
            ? committedSnapshot.result.execution_mode === "demo"
              ? "Demo figure ready"
              : "Checked and saved"
            : "Ready to begin";
  const statusTone =
    errorMessage != null
      ? "error"
      : waitingForInteraction
        ? "attention"
        : isRunning
          ? "working"
          : committedSnapshot?.result != null
            ? "success"
            : "idle";

  return (
    <div className="workspace-conversation" data-workspace-view={workspaceView}>
      <nav className="mobile-workspace-tabs" aria-label="Workspace panels">
        <button
          type="button"
          aria-pressed={workspaceView === "figure"}
          onClick={() => setWorkspaceView("figure")}
        >
          Figure
        </button>
        <button
          type="button"
          aria-pressed={workspaceView === "conversation"}
          onClick={() => setWorkspaceView("conversation")}
        >
          Conversation{waitingForInteraction ? " · input needed" : ""}
        </button>
      </nav>
      <ResizablePanels
        className="workspace-layout"
        direction="horizontal"
        label="Resize conversation panel"
        storageKey="vis-platform.conversation-width"
        firstMinimum={360}
        secondMinimum={310}
        secondMaximum={680}
      >
        <PlotCanvas
          committedSnapshot={committedSnapshot}
          provisionalPreview={provisionalPreview}
          currentBrief={figureBrief}
          statusMessage={statusMessage}
          statusTone={statusTone}
          progressValue={progressValue}
          isRunning={activeRun !== null || plotMutationPending}
          canCancel={activeRun !== null}
          isCancelling={isCancelling}
          onCancel={handleCancel}
          onApplyParameters={applyParameters}
          onSelectVersion={selectVersion}
          onRestoreVersion={restoreVersion}
          onUseResult={useAnalysisResult}
        />
        <ConversationPanel
          projectId={projectId}
          onUploadReference={async (file, signal, requestId) =>
            uploadReferenceImage(await ensureProject(), file, signal, requestId)
          }
          onDeleteReference={deleteReferenceImage}
          draftRequest={draftRequest}
          onUseResult={useAnalysisResult}
          dataSelectionLabel={
            selectedResultIds.length
              ? "Analysis selected"
              : selectedDatasetIds.length
                ? "Data selected"
                : undefined
          }
          dataSelector={
            <DatasetSelector
              projectId={projectId}
              ensureProject={ensureProject}
              selectedIds={selectedDatasetIds}
              resultIds={selectedResultIds}
              onSelect={(ids) => {
                setSelectedDatasetIds(ids);
                setSelectedResultIds([]);
              }}
              onUseResult={useAnalysisResult}
              disabled={isRunning || waitingForInteraction}
            />
          }
          committedSnapshot={committedSnapshot}
          activeSnapshot={activeSnapshot}
          messages={messages}
          traceTargets={traceTargets}
          activities={planner.turns}
          plannerQuestion={planner.pendingQuestion}
          plannerConnectionError={planner.connectionError}
          onPlannerAnswer={handlePlannerAnswer}
          onPlannerCancel={planner.cancel}
          onReconnect={planner.reconnect}
          onCancel={handleCancel}
          progressMessage={progressMessage}
          progressValue={progressValue}
          isRunning={isRunning}
          interactionBusy={interactionBusy}
          interactionError={interactionError}
          onSubmit={submitRequest}
          onAnswerQuestion={handleQuestionAnswer}
          onDecideApproval={handleApprovalDecision}
        />
      </ResizablePanels>
    </div>
  );
}

function traceTargetFromError(
  error: unknown,
  request: string,
): DeveloperTraceTarget | null {
  if (!(error instanceof ApiClientError) || error.details == null) {
    return null;
  }
  const turnId = error.details.turn_id;
  const parsedTrace = apiPathSchema.safeParse(error.details.trace);
  if (typeof turnId !== "string" || !parsedTrace.success) {
    return null;
  }
  return { turnId, traceHref: parsedTrace.data, request };
}

function messageForError(error: unknown): string {
  if (error instanceof ApiClientError || error instanceof Error) {
    return error.message;
  }
  return "An unexpected error occurred.";
}

/** A conversation is named after its first message. */
function conversationTitle(text: string): string {
  const title = text.replace(/\s+/g, " ").trim();
  if (!title) return "Plot reference";
  return title.length > 80 ? title.slice(0, 79).trimEnd() + "…" : title;
}

function readSessionIds(key: string): string[] {
  try {
    const value: unknown = JSON.parse(
      window.sessionStorage.getItem(key) ?? "[]",
    );
    return Array.isArray(value) &&
      value.every((item) => typeof item === "string")
      ? value
      : [];
  } catch {
    return [];
  }
}

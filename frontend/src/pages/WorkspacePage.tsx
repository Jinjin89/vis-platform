import { DatasetSelector } from "../features/datasets/DatasetSelector";
import {
  uploadReferenceImage,
  deleteReferenceImage,
} from "../api/referenceImages";
import type { ReferenceImage } from "../api/schemas/referenceImages";
import type { AnalysisResult } from "../api/schemas/datasets";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";

import {
  ApiClientError,
  answerQuestion,
  cancelPlotRun,
  startAssistantTurn,
  createProject,
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
import { ResizablePanels } from "../components/ResizablePanels";
import { LogoMark } from "../components/Icons";
import { WorkspaceSwitcher } from "../components/WorkspaceSwitcher";
import { ConversationPanel } from "../features/plot-run/ConversationPanel";
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

export function WorkspacePage() {
  const [projectId, setProjectId] = useState<string | null>(() => {
    try {
      return window.sessionStorage.getItem("vis-platform.project-id");
    } catch {
      return null;
    }
  });
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
  const projectCreation = useRef<Promise<string> | null>(null);
  const submissionBusy = useRef(false);
  const lastSubmission = useRef<{ fingerprint: string; key: string } | null>(
    null,
  );
  const queryClient = useQueryClient();
  useEffect(() => {
    try {
      if (projectId)
        window.sessionStorage.setItem("vis-platform.project-id", projectId);
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
  }, [projectId, selectedDatasetIds, selectedResultIds]);
  async function ensureProject(): Promise<string> {
    if (projectId) return projectId;
    if (!projectCreation.current)
      projectCreation.current = createProject()
        .then((project) => {
          setProjectId(project.project_id);
          return project.project_id;
        })
        .catch((error) => {
          projectCreation.current = null;
          throw error;
        });
    return projectCreation.current;
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
    useState<PlotRunSnapshot | null>(null);
  const [activeSnapshot, setActiveSnapshot] = useState<PlotRunSnapshot | null>(
    null,
  );
  const [activeRun, setActiveRun] = useState<PlotRunAccepted | null>(null);
  const [provisionalPreview, setProvisionalPreview] =
    useState<ArtifactReference | null>(null);
  const [messages, setMessages] = useState<ConversationMessage[]>([]);
  const [traceTargets, setTraceTargets] = useState<DeveloperTraceTarget[]>([]);
  const [figureBrief, setFigureBrief] = useState<string | undefined>();
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
  const messageSequence = useRef(0);
  const finalizedRuns = useRef(new Set<string>());
  const recordedInteractions = useRef(new Set<string>());
  const runTurns = useRef(new Map<string, string>());
  const restoredRequests = useRef(new Set<string>());
  const [workspaceView, setWorkspaceView] = useState<"figure" | "conversation">(
    "conversation",
  );

  useEffect(
    () => () => {
      stopListening();
    },
    [],
  );

  const turnMutation = useMutation({
    mutationFn: async ({
      text,
      images,
    }: {
      text: string;
      images: ReferenceImage[];
    }) => {
      const activeProjectId = await ensureProject();
      const fingerprint = JSON.stringify({
        activeProjectId,
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
      );
      lastSubmission.current = null;
      return { submission, projectId: activeProjectId };
    },
  });

  const planner = useAssistantPlanner({
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
    onRestore: (restoredProject, text, turnId, baseRunId, images) => {
      setProjectId(restoredProject);
      if (!restoredRequests.current.has(turnId)) {
        restoredRequests.current.add(turnId);
        appendMessage("user", text, "default", turnId, undefined, images);
      }
      if (baseRunId)
        void getPlotRun(`/api/v1/plot-runs/${encodeURIComponent(baseRunId)}`)
          .then((snapshot) => {
            if (
              snapshot.project_id === restoredProject &&
              snapshot.status === "completed"
            ) {
              setCommittedSnapshot(snapshot);
              setFigureBrief(snapshot.result?.title ?? undefined);
            }
          })
          .catch(() => undefined);
    },
  });
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
      const labels = pending.question.questions.map((question) => {
        const answer = answers.find(
          (value) => value.question_id === question.question_id,
        )!;
        return (
          answer.free_text ||
          question.choices
            .filter((choice) => answer.choice_ids.includes(choice.choice_id))
            .map((choice) => choice.label)
            .join(", ")
        );
      });
      recordInteraction(
        pending.question.interaction_id,
        pending.question.questions.map((question) => question.prompt).join(" "),
        labels.join("; "),
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
      planner.track(
        result.submission,
        result.projectId,
        text,
        committedSnapshot?.run_id,
        images,
      );
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

    if (snapshot.status === "completed" && snapshot.result != null) {
      setCommittedSnapshot(snapshot);
      setWorkspaceView("figure");
      if (snapshot.result.title != null) setFigureBrief(snapshot.result.title);
      setErrorMessage(null);
      if (snapshot.result.execution_mode === "demo") {
        setProgressMessage("Demonstration figure ready");
        appendMessage(
          "assistant",
          "The demonstration figure is ready. Fine-tune it below or export the figure.",
          "default",
          runTurns.current.get(snapshot.run_id),
        );
      } else {
        setProgressMessage("Figure checked and saved");
        appendMessage(
          "assistant",
          "Your figure is ready. Its data, analysis, and parameters are saved with this version.",
          "default",
          runTurns.current.get(snapshot.run_id),
        );
      }
    } else if (
      snapshot.status === "completed" &&
      snapshot.analysis_results?.length
    ) {
      setErrorMessage(null);
      setProgressMessage("Analysis saved");
      appendMessage(
        "assistant",
        "Your analysis is saved. You can inspect its outputs or use them in a figure.",
        "default",
        runTurns.current.get(snapshot.run_id),
        snapshot.analysis_results,
      );
    } else if (snapshot.status === "failed") {
      const message = snapshot.failure?.message ?? "The figure run failed.";
      appendMessage(
        "assistant",
        message +
          (snapshot.analysis_results?.length
            ? " Your completed analysis is saved below."
            : ""),
        "error",
        runTurns.current.get(snapshot.run_id),
        snapshot.analysis_results,
      );
      setErrorMessage(message);
      setProgressValue(0);
    } else if (snapshot.status === "cancelled") {
      appendMessage(
        "assistant",
        "I stopped this run. Your last saved figure is unchanged.",
      );
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
    <main className="app-shell" data-workspace-view={workspaceView}>
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
    </main>
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

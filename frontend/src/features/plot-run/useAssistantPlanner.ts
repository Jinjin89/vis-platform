import { useEffect, useRef, useState } from "react";
import {
  referenceImageSchema,
  type ReferenceImage,
} from "../../api/schemas/referenceImages";
import {
  answerPlanner,
  cancelAssistant,
  createRunEventSource,
  getAssistantState,
} from "../../api/client";
import {
  assistantTurnAcceptedSchema,
  assistantTurnSnapshotSchema,
  type AssistantTurnAccepted,
  type AssistantTurnResponse,
  type AssistantTurnSnapshot,
} from "../../api/schemas/plotRun";
import {
  plannerQuestionsSchema,
  type PlannerAnswer,
} from "../../api/schemas/planner";
import type { AssistantActivityTurn, PendingPlannerQuestion } from "./types";

const STORAGE_KEY = "vis-platform.pending-assistant";
type Tracked = {
  accepted: AssistantTurnAccepted;
  projectId: string;
  text: string;
  baseRunId?: string;
  referenceImages?: ReferenceImage[];
};
type Callbacks = {
  onResponse: (response: AssistantTurnResponse, text: string) => void;
  onError: (message: string, turnId?: string) => void;
  onCancelled?: (turnId: string) => void;
  onRestore: (
    projectId: string,
    text: string,
    turnId: string,
    baseRunId?: string,
    referenceImages?: ReferenceImage[],
  ) => void;
  onReferences?: (turnId: string, images: ReferenceImage[]) => void;
};

export function useAssistantPlanner(callbacks: Callbacks) {
  const handlers = useRef(callbacks);
  handlers.current = callbacks;
  const [turns, setTurns] = useState<AssistantActivityTurn[]>([]);
  const [pendingQuestion, setPendingQuestion] =
    useState<PendingPlannerQuestion | null>(null);
  const [working, setWorking] = useState(false);
  const [connectionError, setConnectionError] = useState<string | null>(null);
  const source = useRef<EventSource | null>(null);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const tracked = useRef<Tracked | null>(null);
  const delivered = useRef(new Set<string>());
  const revisions = useRef(new Map<string, number>());
  const mounted = useRef(true);

  function stop() {
    source.current?.close();
    source.current = null;
    if (timer.current !== null) clearTimeout(timer.current);
    timer.current = null;
  }
  function remember(record: Tracked | null) {
    try {
      if (record)
        window.sessionStorage.setItem(STORAGE_KEY, JSON.stringify(record));
      else window.sessionStorage.removeItem(STORAGE_KEY);
    } catch {
      /* This session still works without browser storage. */
    }
  }
  function upsert(turn: AssistantActivityTurn) {
    setTurns((current) =>
      current.some((item) => item.turnId === turn.turnId)
        ? current.map((item) => (item.turnId === turn.turnId ? turn : item))
        : [...current, turn],
    );
  }
  function receive(snapshot: AssistantTurnSnapshot) {
    const record = tracked.current;
    if (
      !mounted.current ||
      record?.accepted.turn_id !== snapshot.turn_id ||
      record.projectId !== snapshot.project_id
    )
      return;
    if (snapshot.revision < (revisions.current.get(snapshot.turn_id) ?? -1))
      return;
    revisions.current.set(snapshot.turn_id, snapshot.revision);
    handlers.current.onReferences?.(
      snapshot.turn_id,
      snapshot.reference_images ?? [],
    );
    setConnectionError(null);
    upsert({
      turnId: snapshot.turn_id,
      request: snapshot.request_text,
      status: snapshot.status,
      activity: snapshot.activity ?? [],
      traceHref: record.accepted.links.trace,
      runStatus: snapshot.run_status,
    });
    if (snapshot.status === "awaiting_input" && snapshot.question) {
      setPendingQuestion({
        turnId: snapshot.turn_id,
        projectId: snapshot.project_id,
        question: plannerQuestionsSchema.parse(snapshot.question),
      });
      setWorking(false);
      stop();
      return;
    }
    if (snapshot.status === "running") {
      setWorking(true);
      return;
    }
    setWorking(false);
    setPendingQuestion(null);
    if (
      snapshot.status === "completed" &&
      snapshot.response &&
      !delivered.current.has(snapshot.turn_id)
    ) {
      delivered.current.add(snapshot.turn_id);
      handlers.current.onResponse(snapshot.response, record.text);
    }
    if (
      snapshot.status === "failed" &&
      !delivered.current.has(snapshot.turn_id)
    ) {
      delivered.current.add(snapshot.turn_id);
      handlers.current.onError(
        snapshot.error?.message ?? "The assistant request failed.",
        snapshot.turn_id,
      );
    }
    if (
      snapshot.status === "cancelled" &&
      !delivered.current.has(snapshot.turn_id)
    ) {
      delivered.current.add(snapshot.turn_id);
      handlers.current.onCancelled?.(snapshot.turn_id);
    }
    if (
      snapshot.status === "failed" ||
      snapshot.status === "cancelled" ||
      !snapshot.run_status ||
      ["completed", "failed", "cancelled"].includes(snapshot.run_status)
    ) {
      stop();
      remember(null);
      tracked.current = null;
    }
  }
  function poll(record: Tracked, failures = 0) {
    if (
      !mounted.current ||
      tracked.current?.accepted.turn_id !== record.accepted.turn_id
    )
      return;
    if (timer.current !== null) clearTimeout(timer.current);
    timer.current = setTimeout(
      async () => {
        if (
          tracked.current?.accepted.turn_id !== record.accepted.turn_id ||
          !record.accepted.links.status
        )
          return;
        try {
          const snapshot = await getAssistantState(
            record.accepted.links.status,
          );
          receive(snapshot);
          if (tracked.current && snapshot.status !== "awaiting_input")
            poll(record, 0);
        } catch {
          if (failures < 4) poll(record, failures + 1);
          else {
            setConnectionError(
              "Connection interrupted. Reconnect to recover this request.",
            );
            setWorking(false);
          }
        }
      },
      Math.min(500 * 2 ** failures, 4000),
    );
  }
  function connect(record: Tracked) {
    stop();
    tracked.current = record;
    remember(record);
    setConnectionError(null);
    if (!record.accepted.links.events || !record.accepted.links.status)
      throw new Error("Assistant activity links are missing.");
    const stream = createRunEventSource(record.accepted.links.events);
    source.current = stream;
    stream.addEventListener("assistant.updated", (event) => {
      try {
        receive(
          assistantTurnSnapshotSchema.parse(
            JSON.parse((event as MessageEvent<string>).data),
          ),
        );
      } catch {
        stream.close();
        poll(record);
      }
    });
    stream.onerror = () => {
      stream.close();
      if (tracked.current?.accepted.turn_id === record.accepted.turn_id)
        poll(record);
    };
    void getAssistantState(record.accepted.links.status)
      .then(receive)
      .catch(() => poll(record));
  }
  function track(
    submission: AssistantTurnAccepted | AssistantTurnResponse,
    projectId: string,
    text: string,
    baseRunId?: string,
    referenceImages: ReferenceImage[] = [],
  ) {
    if ("outcome" in submission) {
      const waiting = submission.outcome === "question" && submission.question;
      upsert({
        turnId: submission.turn_id,
        request: text,
        status: waiting ? "awaiting_input" : "completed",
        activity: submission.activity ?? [],
        traceHref: submission.links.trace,
      });
      setWorking(false);
      if (waiting) {
        const record: Tracked = {
          accepted: {
            schema_version: "1.0",
            turn_id: submission.turn_id,
            status: "running",
            links: submission.links,
          },
          projectId,
          text,
          baseRunId,
          referenceImages,
        };
        tracked.current = record;
        remember(record);
        setPendingQuestion({
          turnId: submission.turn_id,
          projectId,
          question: plannerQuestionsSchema.parse(submission.question),
        });
      } else if (!delivered.current.has(submission.turn_id)) {
        delivered.current.add(submission.turn_id);
        handlers.current.onResponse(submission, text);
      }
      return;
    }
    setWorking(true);
    setPendingQuestion(null);
    upsert({
      turnId: submission.turn_id,
      request: text,
      status: "running",
      activity: [],
      traceHref: submission.links.trace,
    });
    connect({
      accepted: submission,
      projectId,
      text,
      baseRunId,
      referenceImages,
    });
  }
  async function answer(answers: PlannerAnswer[]) {
    if (!pendingQuestion || !tracked.current) return false;
    const record = tracked.current;
    const accepted = await answerPlanner(
      pendingQuestion.turnId,
      pendingQuestion.projectId,
      pendingQuestion.question.interaction_id,
      answers,
    );
    setPendingQuestion(null);
    setWorking(true);
    connect({ ...record, accepted });
    return true;
  }
  async function cancel() {
    const path = tracked.current?.accepted.links.cancel;
    if (path) receive(await cancelAssistant(path));
  }
  function reconnect() {
    if (tracked.current) connect(tracked.current);
  }
  useEffect(() => {
    mounted.current = true;
    try {
      const encoded = window.sessionStorage.getItem(STORAGE_KEY);
      if (encoded) {
        const saved = JSON.parse(encoded) as Tracked;
        const accepted = assistantTurnAcceptedSchema.parse(saved.accepted);
        if (
          typeof saved.projectId === "string" &&
          typeof saved.text === "string"
        ) {
          handlers.current.onRestore(
            saved.projectId,
            saved.text,
            accepted.turn_id,
            saved.baseRunId,
            referenceImageSchema.array().parse(saved.referenceImages ?? []),
          );
          connect({ ...saved, accepted });
        }
      }
    } catch {
      remember(null);
    }
    return () => {
      mounted.current = false;
      stop();
    };
  }, []);
  return {
    turns,
    pendingQuestion,
    working,
    connectionError,
    track,
    answer,
    cancel,
    reconnect,
  };
}

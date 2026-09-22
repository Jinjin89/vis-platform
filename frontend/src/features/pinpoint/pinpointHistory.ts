import type { PlotMark } from "../../api/pinpoint";
import type { AssistantTurnAccepted } from "../../api/schemas/plotRun";

export type PinpointMessage = {
  id: string;
  role: "user" | "assistant";
  text: string;
  /** The marks a request referred to, as placed on `versionId`. */
  marks?: PlotMark[];
  versionId?: string | null;
  tone?: "error";
};

/** The request still being worked on, so a reload reconnects to it. */
export type PendingRequest = {
  turn: AssistantTurnAccepted;
  prompt: string;
  versionId: string | null;
};

export type PinpointConversation = {
  messages: PinpointMessage[];
  pending: PendingRequest | null;
};

/** The conversation about a plot that does not exist yet. */
export const NEW_PLOT = "new";
const LIMIT = 100;
const empty: PinpointConversation = { messages: [], pending: null };

const storageKey = (projectId: string, plotId: string) =>
  `vis-platform.pinpoint.${projectId}.${plotId}`;

/** Conversations stay in this browser, one per plot, like canvases. */
export function readConversation(
  projectId: string,
  plotId: string,
): PinpointConversation {
  try {
    const stored = window.localStorage.getItem(storageKey(projectId, plotId));
    if (!stored) return empty;
    const parsed = JSON.parse(stored) as Partial<PinpointConversation>;
    return {
      messages: Array.isArray(parsed.messages) ? parsed.messages : [],
      pending: parsed.pending ?? null,
    };
  } catch {
    return empty;
  }
}

export function writeConversation(
  projectId: string,
  plotId: string,
  conversation: PinpointConversation,
) {
  try {
    const key = storageKey(projectId, plotId);
    if (!conversation.messages.length && !conversation.pending)
      window.localStorage.removeItem(key);
    else
      window.localStorage.setItem(
        key,
        JSON.stringify({
          ...conversation,
          messages: conversation.messages.slice(-LIMIT),
        }),
      );
  } catch {
    /* Without storage the conversation lasts for this page only. */
  }
}

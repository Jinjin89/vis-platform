import { useEffect, useRef, type ReactNode } from "react";
import type { PlotMark } from "../../api/pinpoint";
import { describeMark } from "./marks";
import type { PinpointMessage } from "./pinpointHistory";

/** The conversation about one plot, and the request box that sends the current marks. */
export function PinpointConversation({
  messages,
  marks,
  status,
  busy,
  canMark,
  draft,
  onDraft,
  onRemoveMark,
  onClearMarks,
  onSend,
}: {
  messages: PinpointMessage[];
  marks: PlotMark[];
  /** The request being worked on. */
  status: ReactNode;
  busy: boolean;
  canMark: boolean;
  draft: string;
  onDraft: (text: string) => void;
  onRemoveMark: (number: number) => void;
  onClearMarks: () => void;
  onSend: (text: string) => void;
}) {
  const end = useRef<HTMLDivElement>(null);
  useEffect(() => {
    end.current?.scrollIntoView?.({ block: "end" });
  }, [messages.length]);
  function send() {
    const text = draft.trim();
    if (text && !busy) onSend(text);
  }
  return (
    <section className="pinpoint-conversation" aria-label="Conversation">
      <div className="pinpoint-messages" aria-live="polite">
        {messages.length ? null : (
          <p className="pinpoint-empty">
            {canMark
              ? "Mark places on the plot, then refer to them by number: “label 1”, “why is 2 so high?”, “zoom into area 3”."
              : "Describe the plot you want. Once it appears, you can mark places on it and talk about them."}
          </p>
        )}
        {messages.map((message) => (
          <article
            key={message.id}
            className="pinpoint-message"
            data-role={message.role}
            data-tone={message.tone}
          >
            {message.marks?.length ? (
              <ul className="pinpoint-message-marks" aria-label="Marks sent">
                {message.marks.map((mark) => (
                  <li key={mark.number}>{describeMark(mark)}</li>
                ))}
              </ul>
            ) : null}
            <p>{message.text}</p>
          </article>
        ))}
        {status}
        <div ref={end} />
      </div>
      <form
        className="pinpoint-composer"
        onSubmit={(event) => {
          event.preventDefault();
          send();
        }}
      >
        {marks.length ? (
          <div className="pinpoint-composer-marks">
            <ul aria-label="Marks to send">
              {marks.map((mark) => (
                <li key={mark.number}>
                  <span>{describeMark(mark)}</span>
                  <button
                    type="button"
                    aria-label={`Remove mark ${mark.number}`}
                    onClick={() => onRemoveMark(mark.number)}
                  >
                    ×
                  </button>
                </li>
              ))}
            </ul>
            <button
              type="button"
              className="pinpoint-link"
              onClick={onClearMarks}
            >
              Clear marks
            </button>
          </div>
        ) : null}
        <textarea
          aria-label="Your request"
          value={draft}
          rows={3}
          placeholder={
            canMark
              ? "Say what you want, e.g. “label 1 and make 2 red”"
              : "Describe a plot to make from your data"
          }
          onChange={(event) => onDraft(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === "Enter" && !event.shiftKey) {
              event.preventDefault();
              send();
            }
          }}
        />
        <button type="submit" disabled={busy || !draft.trim()}>
          {busy ? "Working…" : "Send"}
        </button>
      </form>
    </section>
  );
}

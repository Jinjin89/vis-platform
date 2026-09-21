import { CheckIcon, SparkIcon, SlidersIcon } from "../../components/Icons";
import type { AssistantActivityTurn } from "./types";
import { DeveloperTracePanel } from "./DeveloperTracePanel";

export function AgentActivity({ turn }: { turn: AssistantActivityTurn }) {
  if (!turn.activity.length && turn.status !== "running") return null;
  const running =
    turn.status === "running" ||
    (turn.runStatus != null && ["queued", "running"].includes(turn.runStatus));
  const label =
    turn.status === "awaiting_input"
      ? "Waiting for your choice"
      : turn.status === "failed" || turn.runStatus === "failed"
        ? "Request needs attention"
        : turn.status === "cancelled"
          ? "Request stopped"
          : running
            ? "Working on your request"
            : `Activity · ${turn.activity.length} steps`;
  const duration = turn.activity.reduce(
    (sum, entry) => sum + (entry.duration_ms ?? 0),
    0,
  );
  return (
    <details className="agent-activity" aria-label="Agent activity">
      <summary>
        <span className="activity-chevron" aria-hidden="true">
          ›
        </span>
        {running ? (
          <span className="activity-spinner" aria-hidden="true" />
        ) : (
          <CheckIcon />
        )}
        <span>{label}</span>
        {duration > 0 ? <small>{(duration / 1000).toFixed(1)}s</small> : null}
      </summary>
      <ol className="activity-steps">
        {turn.activity.map((entry) => (
          <li key={entry.step_id} data-status={entry.status}>
            <span className="activity-step-icon" aria-hidden="true">
              {entry.kind === "agent" ? (
                <SparkIcon />
              ) : entry.kind === "tool" ? (
                <SlidersIcon />
              ) : (
                <CheckIcon />
              )}
            </span>
            <div>
              <div className="activity-step-heading">
                <strong>{entry.label}</strong>
                <span>
                  {entry.status === "completed"
                    ? "Done"
                    : entry.status === "running"
                      ? "Working"
                      : entry.status}
                </span>
              </div>
              <div className="activity-actor">
                {entry.actor}
                {entry.tool_name ? (
                  <>
                    {" "}
                    · <code>{entry.tool_name}</code>
                  </>
                ) : null}
              </div>
              {entry.summary ? <p>{entry.summary}</p> : null}
            </div>
          </li>
        ))}
      </ol>
      {turn.traceHref ? (
        <details className="activity-developer">
          <summary>Developer diagnostics</summary>
          <DeveloperTracePanel
            targets={[
              {
                turnId: turn.turnId,
                traceHref: turn.traceHref,
                request: turn.request,
              },
            ]}
          />
        </details>
      ) : null}
    </details>
  );
}

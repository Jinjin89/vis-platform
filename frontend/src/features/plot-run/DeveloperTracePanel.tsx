import { useEffect, useState } from "react";
import type { FormEvent } from "react";

import { ApiClientError, getDeveloperTrace } from "../../api/client";
import type {
  DeveloperTraceEntry,
  DeveloperTraceResponse,
} from "../../api/schemas/plotRun";
import type { DeveloperTraceTarget } from "./types";

const TRACE_TOKEN_STORAGE_KEY = "vis-platform.developer-trace-token";

type TraceLoadResult =
  | { status: "ready"; trace: DeveloperTraceResponse }
  | { status: "error"; message: string };

type DeveloperTracePanelProps = {
  targets: DeveloperTraceTarget[];
};

export function DeveloperTracePanel({ targets }: DeveloperTracePanelProps) {
  const [accessToken, setAccessToken] = useState(readSessionToken);
  const [tokenDraft, setTokenDraft] = useState("");
  const [refreshVersion, setRefreshVersion] = useState(0);
  const [isLoading, setIsLoading] = useState(false);
  const [results, setResults] = useState<Record<string, TraceLoadResult>>({});

  useEffect(() => {
    if (accessToken === null || targets.length === 0) {
      return;
    }

    let ignore = false;
    setIsLoading(true);
    void Promise.all(
      targets.map(async (target): Promise<[string, TraceLoadResult]> => {
        try {
          const trace = await getDeveloperTrace(target.traceHref, accessToken);
          return [target.turnId, { status: "ready", trace }];
        } catch (error) {
          return [
            target.turnId,
            { status: "error", message: traceErrorMessage(error) },
          ];
        }
      }),
    ).then((loaded) => {
      if (!ignore) {
        setResults(Object.fromEntries(loaded));
        setIsLoading(false);
      }
    });

    return () => {
      ignore = true;
    };
  }, [accessToken, refreshVersion, targets]);

  function unlockTrace(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const token = tokenDraft.trim();
    if (token.length === 0) {
      return;
    }
    writeSessionToken(token);
    setAccessToken(token);
    setTokenDraft("");
  }

  function lockTrace() {
    removeSessionToken();
    setAccessToken(null);
    setResults({});
  }

  return (
    <section
      className="developer-trace-panel"
      role="tabpanel"
      aria-label="Developer trace"
    >
      <div className="trace-privacy-note">
        <strong>Observable execution trace</strong>
        <p>
          Private model reasoning is not exposed. This view contains sanitized
          model input and output, intent, routing, tool activity, timing, and
          errors.
        </p>
      </div>

      {accessToken === null ? (
        <form className="trace-token-form" onSubmit={unlockTrace}>
          <label htmlFor="developer-trace-token">Developer trace token</label>
          <input
            id="developer-trace-token"
            type="password"
            autoComplete="off"
            value={tokenDraft}
            onChange={(event) => setTokenDraft(event.target.value)}
            placeholder="Enter the server trace token"
          />
          <button type="submit" disabled={tokenDraft.trim().length === 0}>
            Unlock trace
          </button>
          <small>The token is kept only for this browser session.</small>
        </form>
      ) : (
        <>
          <div className="trace-toolbar">
            <span>{isLoading ? "Loading trace…" : "Trace unlocked"}</span>
            <button
              type="button"
              onClick={() => setRefreshVersion((value) => value + 1)}
              disabled={isLoading || targets.length === 0}
            >
              Refresh
            </button>
            <button type="button" onClick={lockTrace}>
              Lock
            </button>
          </div>

          {targets.length === 0 ? (
            <p className="trace-empty">Send a request to create a trace.</p>
          ) : (
            <div className="trace-turns">
              {targets.map((target, index) => (
                <TraceTurn
                  key={target.turnId}
                  target={target}
                  turnNumber={index + 1}
                  result={results[target.turnId]}
                  isLoading={isLoading}
                />
              ))}
            </div>
          )}
        </>
      )}
    </section>
  );
}

type TraceTurnProps = {
  target: DeveloperTraceTarget;
  turnNumber: number;
  result: TraceLoadResult | undefined;
  isLoading: boolean;
};

function TraceTurn({ target, turnNumber, result, isLoading }: TraceTurnProps) {
  return (
    <section className="trace-turn" aria-label={`Trace for turn ${turnNumber}`}>
      <header>
        <strong>Turn {turnNumber}</strong>
        <span>{target.request}</span>
      </header>

      {result?.status === "error" ? (
        <p className="trace-error" role="alert">
          {result.message}
        </p>
      ) : null}

      {result?.status === "ready" ? (
        <div className="trace-entries">
          {[...result.trace.entries]
            .sort((left, right) => left.sequence - right.sequence)
            .map((entry) => (
              <TraceEntry key={entry.trace_id} entry={entry} />
            ))}
        </div>
      ) : null}

      {result === undefined && isLoading ? (
        <p className="trace-loading">Loading this turn…</p>
      ) : null}
    </section>
  );
}

function TraceEntry({ entry }: { entry: DeveloperTraceEntry }) {
  const intentKind = stringValue(entry.output, "kind");
  const decisionSummary = stringValue(entry.output, "decision_summary");
  const route = stringValue(entry.output, "route");

  return (
    <details className="trace-entry">
      <summary>
        <span className="trace-sequence">{entry.sequence}</span>
        <span className="trace-status" data-status={entry.status} />
        <strong>{humanize(entry.name)}</strong>
        <span>{humanize(entry.kind)}</span>
        {entry.duration_ms != null ? (
          <span>{entry.duration_ms.toLocaleString()} ms</span>
        ) : null}
      </summary>
      <div className="trace-entry-body">
        <dl>
          <div>
            <dt>Actor</dt>
            <dd>{humanize(entry.actor)}</dd>
          </div>
          <div>
            <dt>Status</dt>
            <dd>{humanize(entry.status)}</dd>
          </div>
        </dl>

        {entry.kind === "intent_decision" &&
        (intentKind != null || decisionSummary != null) ? (
          <div className="trace-decision">
            {intentKind != null ? (
              <strong>{humanize(intentKind)}</strong>
            ) : null}
            {decisionSummary != null ? <p>{decisionSummary}</p> : null}
          </div>
        ) : null}

        {entry.kind === "routing" && route != null ? (
          <p className="trace-route">
            Route: <strong>{humanize(route)}</strong>
          </p>
        ) : null}

        <TracePayload label="Sanitized input" value={entry.input} />
        <TracePayload label="Structured output" value={entry.output} />
        <TracePayload label="Error" value={entry.error} tone="error" />
      </div>
    </details>
  );
}

type TracePayloadProps = {
  label: string;
  value: Record<string, unknown> | null | undefined;
  tone?: "default" | "error";
};

function TracePayload({ label, value, tone = "default" }: TracePayloadProps) {
  if (value == null) {
    return null;
  }
  return (
    <section className="trace-payload" data-tone={tone}>
      <strong>{label}</strong>
      <pre>{JSON.stringify(value, null, 2)}</pre>
    </section>
  );
}

function stringValue(
  value: Record<string, unknown> | null | undefined,
  key: string,
): string | null {
  const candidate = value?.[key];
  return typeof candidate === "string" ? candidate : null;
}

function humanize(value: string): string {
  return value.replaceAll("_", " ");
}

function readSessionToken(): string | null {
  try {
    return window.sessionStorage.getItem(TRACE_TOKEN_STORAGE_KEY);
  } catch {
    return null;
  }
}

function writeSessionToken(token: string) {
  try {
    window.sessionStorage.setItem(TRACE_TOKEN_STORAGE_KEY, token);
  } catch {
    // Trace access still works for this page when session storage is unavailable.
  }
}

function removeSessionToken() {
  try {
    window.sessionStorage.removeItem(TRACE_TOKEN_STORAGE_KEY);
  } catch {
    // The in-memory token is cleared below even when storage is unavailable.
  }
}

function traceErrorMessage(error: unknown): string {
  if (error instanceof ApiClientError) {
    if (error.code === "TRACE_ACCESS_DENIED") {
      return "Trace access was denied. Lock the trace and enter the correct token.";
    }
    return error.message;
  }
  if (error instanceof Error) {
    return error.message;
  }
  return "The developer trace could not be loaded.";
}

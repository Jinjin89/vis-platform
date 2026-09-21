import { useRef, useState } from "react";
import Markdown from "react-markdown";
import { resolveArtifactUrl } from "../../api/client";
import {
  figureForBlock,
  type ReportDocument,
  type ReportSection,
  type ReportBlock,
  type SlideFrame,
} from "../../api/schemas/reports";

export function defaultFrames(
  section: ReportSection,
): Record<string, SlideFrame> {
  const result: Record<string, SlideFrame> = {};
  const blocks = section.blocks;
  const layout = section.slide?.layout ?? "figure-summary";
  const figure = blocks.find((b) => b.type === "figure" || b.type === "table");
  const texts = blocks.filter((b) => b !== figure);
  for (const [i, block] of blocks.entries()) {
    if (layout === "title" || layout === "statement") {
      result[block.id] = {
        x: 0.08,
        y:
          (layout === "title" ? 0.57 : 0.38) +
          (i * (layout === "title" ? 0.28 : 0.5)) / Math.max(blocks.length, 1),
        width: 0.84,
        height: (layout === "title" ? 0.26 : 0.48) / Math.max(blocks.length, 1),
      };
    } else if (layout === "figure-summary" && figure && blocks.length <= 3) {
      result[block.id] =
        block === figure
          ? {
              x: 0.065,
              y: 0.27,
              width: texts.length ? 0.57 : 0.87,
              height: 0.61,
            }
          : {
              x: 0.68,
              y: 0.3 + (texts.indexOf(block) * 0.52) / texts.length,
              width: 0.25,
              height: 0.5 / texts.length,
            };
    } else {
      const columns = blocks.length === 1 ? 1 : 2;
      const rows = Math.ceil(blocks.length / columns);
      result[block.id] = {
        x: 0.07 + (i % columns) * 0.45,
        y: 0.28 + (Math.floor(i / columns) * 0.59) / rows,
        width: columns === 1 ? 0.86 : 0.41,
        height: 0.56 / rows,
      };
    }
  }
  return { ...result, ...section.slide?.frames };
}
export function SlideCanvas({
  document,
  section,
  index,
  thumbnail = false,
  presenting = false,
  selectedId,
  onSelect,
  onEdit,
  onMenu,
  onFrame,
}: {
  document: ReportDocument;
  section: ReportSection;
  index: number;
  thumbnail?: boolean;
  presenting?: boolean;
  selectedId?: string | null;
  onSelect?: (block: ReportBlock) => void;
  onEdit?: (block: ReportBlock) => void;
  onMenu?: (event: React.MouseEvent<HTMLElement>, block: ReportBlock) => void;
  onFrame?: (blockId: string, frame: SlideFrame) => void;
}) {
  const ref = useRef<HTMLDivElement>(null);
  const [draft, setDraft] = useState<Record<string, SlideFrame>>({});
  const frames = { ...defaultFrames(section), ...draft };
  const interactive = !thumbnail && !presenting;
  function drag(
    event: React.PointerEvent<HTMLButtonElement>,
    blockId: string,
    resize = false,
  ) {
    event.preventDefault();
    event.stopPropagation();
    const bounds = ref.current!.getBoundingClientRect();
    const initial = frames[blockId]!;
    const start = { x: event.clientX, y: event.clientY };
    let next = initial;
    const target = event.currentTarget;
    target.setPointerCapture(event.pointerId);
    const move = (e: PointerEvent) => {
      const dx = (e.clientX - start.x) / bounds.width,
        dy = (e.clientY - start.y) / bounds.height;
      next = resize
        ? {
            ...initial,
            width: Math.max(0.12, Math.min(1 - initial.x, initial.width + dx)),
            height: Math.max(0.1, Math.min(1 - initial.y, initial.height + dy)),
          }
        : {
            ...initial,
            x: Math.max(0, Math.min(1 - initial.width, initial.x + dx)),
            y: Math.max(0, Math.min(1 - initial.height, initial.y + dy)),
          };
      setDraft({ [blockId]: next });
    };
    const finish = () => {
      target.removeEventListener("pointermove", move);
      target.removeEventListener("pointerup", finish);
      target.removeEventListener("pointercancel", cancel);
      onFrame?.(blockId, next);
      setDraft({});
    };
    const cancel = () => {
      target.removeEventListener("pointermove", move);
      target.removeEventListener("pointerup", finish);
      target.removeEventListener("pointercancel", cancel);
      setDraft({});
    };
    target.addEventListener("pointermove", move);
    target.addEventListener("pointerup", finish);
    target.addEventListener("pointercancel", cancel);
  }
  return (
    <div
      ref={ref}
      className={`slide-canvas ${thumbnail ? "is-thumbnail" : ""}`}
      data-theme={document.content.presentation?.theme ?? "paper"}
      data-layout={section.slide?.layout ?? "figure-summary"}
    >
      <div className="slide-rule" />
      <div className="slide-eyebrow">{document.title}</div>
      <h2 className="slide-heading">{section.title}</h2>
      {section.blocks.map((block) => {
        const frame = frames[block.id]!;
        const figure =
          block.type === "figure" ? figureForBlock(document, block) : undefined;
        const image =
          block.type === "figure" && block.image_id
            ? document.images[block.image_id]
            : undefined;
        return (
          <div
            key={block.id}
            className={`slide-element slide-element-${block.type} ${interactive && selectedId === block.id ? "is-selected" : ""}`}
            style={{
              left: `${frame.x * 100}%`,
              top: `${frame.y * 100}%`,
              width: `${frame.width * 100}%`,
              height: `${frame.height * 100}%`,
            }}
            tabIndex={interactive ? 0 : undefined}
            role={interactive ? "group" : undefined}
            aria-label={interactive ? `${block.type} element` : undefined}
            onClick={() => onSelect?.(block)}
            onDoubleClick={() => onEdit?.(block)}
            onContextMenu={(event) => {
              if (interactive) {
                event.preventDefault();
                onSelect?.(block);
                onMenu?.(event, block);
              }
            }}
            onKeyDown={(event) => {
              if (!interactive) return;
              if (event.key === "Enter") {
                event.preventDefault();
                onEdit?.(block);
              }
              if (
                event.altKey &&
                ["ArrowLeft", "ArrowRight", "ArrowUp", "ArrowDown"].includes(
                  event.key,
                )
              ) {
                event.preventDefault();
                onFrame?.(block.id, {
                  ...frame,
                  x: Math.max(
                    0,
                    Math.min(
                      1 - frame.width,
                      frame.x +
                        (event.key === "ArrowRight"
                          ? 0.01
                          : event.key === "ArrowLeft"
                            ? -0.01
                            : 0),
                    ),
                  ),
                  y: Math.max(
                    0,
                    Math.min(
                      1 - frame.height,
                      frame.y +
                        (event.key === "ArrowDown"
                          ? 0.01
                          : event.key === "ArrowUp"
                            ? -0.01
                            : 0),
                    ),
                  ),
                });
              }
            }}
          >
            {block.type === "text" ? (
              <div className="slide-prose">
                <Markdown disallowedElements={["img"]}>{block.body}</Markdown>
              </div>
            ) : block.type === "figure" ? (
              <figure>
                {figure || image ? (
                  <img
                    draggable={false}
                    src={resolveArtifactUrl(
                      figure?.preview.href ?? image!.links.content,
                    )}
                    alt={figure?.title ?? block.caption ?? "Figure"}
                  />
                ) : (
                  <span>Figure unavailable</span>
                )}
                <figcaption>
                  {figure?.caption ||
                    figure?.preview.description ||
                    block.caption}
                </figcaption>
              </figure>
            ) : (
              <div className="slide-table">
                <strong>{block.title}</strong>
                <table>
                  <thead>
                    <tr>
                      {block.columns.map((c, i) => (
                        <th key={i}>{c}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {block.rows.map((row, i) => (
                      <tr key={i}>
                        {row.map((v, j) => (
                          <td key={j}>{String(v ?? "")}</td>
                        ))}
                      </tr>
                    ))}
                  </tbody>
                </table>
                <small>{block.source_description}</small>
              </div>
            )}
            {interactive && selectedId === block.id ? (
              <>
                <button
                  className="slide-move-handle"
                  aria-label="Drag element"
                  onPointerDown={(e) => drag(e, block.id)}
                >
                  ⠿
                </button>
                <button
                  className="slide-resize-handle"
                  aria-label="Resize element"
                  onPointerDown={(e) => drag(e, block.id, true)}
                  onKeyDown={(e) => {
                    if (
                      [
                        "ArrowLeft",
                        "ArrowRight",
                        "ArrowUp",
                        "ArrowDown",
                      ].includes(e.key)
                    ) {
                      e.preventDefault();
                      e.stopPropagation();
                      onFrame?.(block.id, {
                        ...frame,
                        width: Math.max(
                          0.12,
                          Math.min(
                            1 - frame.x,
                            frame.width +
                              (e.key === "ArrowRight"
                                ? 0.01
                                : e.key === "ArrowLeft"
                                  ? -0.01
                                  : 0),
                          ),
                        ),
                        height: Math.max(
                          0.1,
                          Math.min(
                            1 - frame.y,
                            frame.height +
                              (e.key === "ArrowDown"
                                ? 0.01
                                : e.key === "ArrowUp"
                                  ? -0.01
                                  : 0),
                          ),
                        ),
                      });
                    }
                  }}
                />
              </>
            ) : null}
          </div>
        );
      })}
      {!section.blocks.length && interactive ? (
        <div className="slide-empty">
          <span>Start with a figure, a finding, or an idea.</span>
          <small>Use the toolbar or ask your assistant.</small>
        </div>
      ) : null}
      <div className="slide-footer">
        <span>RESEARCH PRESENTATION</span>
        <span>{String(index + 1).padStart(2, "0")}</span>
      </div>
    </div>
  );
}

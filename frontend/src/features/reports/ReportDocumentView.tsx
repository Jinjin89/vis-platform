import { useEffect, useLayoutEffect, useRef, useState } from "react";
import Markdown from "react-markdown";
import { resolveArtifactUrl } from "../../api/client";
import {
  reportEditActive,
  type ReportOperation,
  type ReportDocument,
} from "../../api/schemas/reports";
import type { ReportEditorTarget } from "./ReportEditorDialog";
import { reportItemNumbers } from "./reportPresentation";

type Props = {
  document: ReportDocument;
  saving: boolean;
  selectedTopic: string | null;
  selectedBlockId?: string;
  selectTopic: (id: string) => void;
  setSelectedTopic: (id: string) => void;
  selectBlock: (sectionId: string, blockId: string) => void;
  compose: (
    sectionId: string,
    kind: "text" | "figure",
    blockId?: string,
  ) => void;
  addTopic: (parentId?: string) => void;
  moveTopic: (index: number, direction: number) => void;
  apply: (operations: ReportOperation[], summary: string) => Promise<boolean>;
  perform: (action: () => Promise<unknown>) => Promise<void>;
  setEditor: (target: ReportEditorTarget) => void;
  setLibraryTopic: (id: string) => void;
  setImageTopic: (id: string) => void;
  setMenu: (menu: {
    x: number;
    y: number;
    topicId: string;
    blockId: string;
    trigger: HTMLElement | null;
  }) => void;
};

export function ReportDocumentView({
  document,
  saving,
  selectedTopic,
  selectedBlockId,
  selectTopic,
  setSelectedTopic,
  selectBlock,
  compose,
  addTopic,
  moveTopic,
  apply,
  perform,
  setEditor,
  setLibraryTopic,
  setImageTopic,
  setMenu,
}: Props) {
  const working = document.edits.filter(
    (edit) => reportEditActive(edit) && edit.kind !== "discussion",
  );
  const figures = reportItemNumbers(document.content, "figure");
  const tables = reportItemNumbers(document.content, "table");
  return (
    <div className="report-layout">
      <aside className="report-outline" aria-label="Report outline">
        <div className="report-outline-title">CONTENTS</div>
        {document.content.sections.map((section) => (
          <button
            type="button"
            key={section.id}
            data-level={section.level}
            aria-current={selectedTopic === section.id ? "true" : undefined}
            onClick={() => selectTopic(section.id)}
          >
            <span>{section.title}</span>
          </button>
        ))}
        <button
          type="button"
          className="report-add-topic"
          disabled={saving}
          onClick={() => addTopic()}
        >
          + Add section
        </button>
      </aside>
      <div className="report-paper-scroll">
        <article className="report-paper" aria-label="Report document">
          <header className="report-document-header">
            <h1>
              <EditableText
                label="Report title"
                value={document.title}
                className="report-title-input"
                onSave={(title) =>
                  perform(() =>
                    apply([{ op: "rename_report", title }], "Renamed report"),
                  )
                }
              />
            </h1>
          </header>
          {document.content.sections.map((section, index) => {
            const Heading = section.level === 1 ? "h2" : "h3";
            const siblings = document.content.sections.filter(
              (item) => item.parent_id === section.parent_id,
            );
            const siblingIndex = siblings.findIndex(
              (item) => item.id === section.id,
            );
            return (
              <section
                key={section.id}
                className="report-topic"
                id={"report-topic-" + section.id}
                data-topic-id={section.id}
                data-level={section.level}
                data-parent-id={section.parent_id ?? undefined}
                data-selected={selectedTopic === section.id}
                onFocus={() => setSelectedTopic(section.id)}
              >
                <div className="report-topic-heading">
                  <Heading aria-label={section.title}>
                    <EditableText
                      id={"report-topic-title-" + section.id}
                      label={`Section ${index + 1} title`}
                      value={section.title}
                      onSave={(title) =>
                        perform(() =>
                          apply(
                            [
                              {
                                op: "rename_section",
                                section_id: section.id,
                                title,
                              },
                            ],
                            "Renamed section",
                          ),
                        )
                      }
                    />
                  </Heading>
                  <div className="report-topic-actions report-editing-tools">
                    <button
                      type="button"
                      aria-label={`Move ${section.title} up`}
                      disabled={saving || siblingIndex === 0}
                      onClick={() => moveTopic(index, -1)}
                    >
                      ↑
                    </button>
                    <button
                      type="button"
                      aria-label={`Move ${section.title} down`}
                      disabled={saving || siblingIndex === siblings.length - 1}
                      onClick={() => moveTopic(index, 1)}
                    >
                      ↓
                    </button>
                    <button
                      type="button"
                      aria-label={`Remove section ${section.title}`}
                      disabled={
                        saving ||
                        working.some((edit) => edit.section_id === section.id)
                      }
                      onClick={() =>
                        void perform(() =>
                          apply(
                            [{ op: "remove_section", section_id: section.id }],
                            "Removed section",
                          ),
                        )
                      }
                    >
                      ×
                    </button>
                  </div>
                </div>
                {!section.blocks.length ? (
                  <p className="report-empty-topic">
                    Describe what you want to add in the assistant.
                  </p>
                ) : null}
                {section.blocks.map((block, blockIndex) => {
                  const busy = working.some(
                    (edit) => edit.block_id === block.id,
                  );
                  const label =
                    block.type === "figure"
                      ? `Figure ${figures.get(block.id)}`
                      : block.type === "table"
                        ? `Table ${tables.get(block.id)}`
                        : `Paragraph ${blockIndex + 1}`;
                  const plot =
                    block.type === "figure" && block.version_id
                      ? document.figures[
                          document.figure_bindings?.[block.id] ??
                            block.version_id!
                        ]
                      : undefined;
                  return (
                    <div
                      className="report-block"
                      key={block.id}
                      data-block-id={block.id}
                      data-kind={block.type}
                      data-selected={selectedBlockId === block.id}
                      tabIndex={0}
                      role="group"
                      aria-label={label}
                      onClick={(event) => {
                        if (
                          (event.target as Element).closest(
                            "button,input,textarea,a",
                          ) ||
                          window.getSelection()?.isCollapsed === false
                        )
                          return;
                        selectBlock(section.id, block.id);
                      }}
                      onKeyDown={(event) => {
                        if (
                          event.target === event.currentTarget &&
                          event.key === "Enter"
                        ) {
                          event.preventDefault();
                          selectBlock(section.id, block.id);
                        }
                      }}
                    >
                      {block.type === "text" ? (
                        <>
                          <div className="report-text-block">
                            <Markdown>{block.body}</Markdown>
                          </div>
                          <div className="report-block-actions report-editing-tools">
                            {document.stale_text_ids.includes(block.id) ? (
                              <span className="report-stale-note">
                                Review interpretation
                              </span>
                            ) : null}
                            <button
                              type="button"
                              disabled={busy}
                              onClick={() =>
                                compose(section.id, "text", block.id)
                              }
                            >
                              Refine paragraph
                            </button>
                            <button
                              type="button"
                              disabled={busy}
                              onClick={() =>
                                setEditor({
                                  kind: "text",
                                  topicId: section.id,
                                  blockId: block.id,
                                })
                              }
                            >
                              Edit directly
                            </button>
                            <button
                              type="button"
                              disabled={busy}
                              onClick={() =>
                                void perform(() =>
                                  apply(
                                    [
                                      {
                                        op: "remove_block",
                                        block_id: block.id,
                                      },
                                    ],
                                    "Removed paragraph",
                                  ),
                                )
                              }
                            >
                              Remove
                            </button>
                          </div>
                        </>
                      ) : block.type === "figure" ? (
                        <figure
                          tabIndex={0}
                          aria-label={label}
                          onContextMenu={(event) => {
                            event.preventDefault();
                            const rect =
                              event.currentTarget.getBoundingClientRect();
                            setMenu({
                              x: event.clientX || rect.left + 30,
                              y: event.clientY || rect.top + 30,
                              topicId: section.id,
                              blockId: block.id,
                              trigger: event.currentTarget,
                            });
                          }}
                        >
                          <div className="report-figure-toolbar report-editing-tools">
                            <button
                              type="button"
                              className="report-figure-menu-trigger"
                              aria-label="Figure actions"
                              aria-haspopup="menu"
                              onClick={(event) => {
                                const rect =
                                  event.currentTarget.getBoundingClientRect();
                                setMenu({
                                  x: rect.right - 220,
                                  y: rect.bottom + 4,
                                  topicId: section.id,
                                  blockId: block.id,
                                  trigger: event.currentTarget,
                                });
                              }}
                            >
                              ⋯
                            </button>
                          </div>
                          <ReportImage
                            key={block.version_id ?? block.image_id}
                            href={
                              plot?.preview.href ??
                              document.images[block.image_id!]!.links.content
                            }
                            alt={
                              plot?.caption ??
                              plot?.preview.description ??
                              block.caption ??
                              label
                            }
                          />
                          <figcaption>
                            <strong>{label}.</strong>
                            {plot ? (
                              <span>
                                {plot.caption ?? plot.preview.description}
                              </span>
                            ) : (
                              <EditableText
                                label="Image caption"
                                value={block.caption}
                                allowEmpty
                                className="report-caption-input"
                                onSave={(caption) =>
                                  perform(() =>
                                    apply(
                                      [
                                        {
                                          op: "replace_block",
                                          section_id: section.id,
                                          block: { ...block, caption },
                                        },
                                      ],
                                      "Updated image caption",
                                    ),
                                  )
                                }
                              />
                            )}
                          </figcaption>
                        </figure>
                      ) : (
                        <div className="report-table">
                          <h3>
                            <strong>{label}.</strong> {block.title}
                          </h3>
                          <div>
                            <table>
                              <thead>
                                <tr>
                                  {block.columns.map((column, i) => (
                                    <th key={i}>{column}</th>
                                  ))}
                                </tr>
                              </thead>
                              <tbody>
                                {block.rows.map((row, i) => (
                                  <tr key={i}>
                                    {row.map((cell, j) => (
                                      <td key={j}>
                                        {cell == null ? "—" : String(cell)}
                                      </td>
                                    ))}
                                  </tr>
                                ))}
                              </tbody>
                            </table>
                          </div>
                          {block.source_description ? (
                            <p className="report-table-note">
                              {block.source_description}
                            </p>
                          ) : null}
                        </div>
                      )}
                    </div>
                  );
                })}
                <div
                  className="report-add-content report-editing-tools"
                  role="group"
                  aria-label={`Add content to ${section.title}`}
                >
                  <span>+</span>
                  <button
                    type="button"
                    onClick={() => compose(section.id, "figure")}
                  >
                    New figure
                  </button>
                  <button
                    type="button"
                    onClick={() =>
                      setEditor({ kind: "text", topicId: section.id })
                    }
                  >
                    Text
                  </button>
                  <button
                    type="button"
                    onClick={() => setLibraryTopic(section.id)}
                  >
                    Saved figure
                  </button>
                  <button
                    type="button"
                    onClick={() => setImageTopic(section.id)}
                  >
                    Image
                  </button>
                  {section.level === 1 ? (
                    <button
                      type="button"
                      aria-label={`Add subsection to ${section.title}`}
                      onClick={() => addTopic(section.id)}
                    >
                      Subsection
                    </button>
                  ) : null}
                </div>
              </section>
            );
          })}
        </article>
        <button
          type="button"
          className="report-paper-add-topic"
          disabled={saving}
          onClick={() => addTopic()}
        >
          + Add a section
        </button>
      </div>
    </div>
  );
}

function EditableText({
  label,
  value,
  onSave,
  className,
  id,
  allowEmpty = false,
}: {
  label: string;
  value: string;
  onSave: (value: string) => Promise<unknown>;
  className?: string;
  id?: string;
  allowEmpty?: boolean;
}) {
  const [draft, setDraft] = useState(value);
  const focused = useRef(false),
    discard = useRef(false);
  const field = useRef<HTMLTextAreaElement>(null);
  useEffect(() => {
    if (!focused.current) setDraft(value);
  }, [value]);
  useLayoutEffect(() => {
    const element = field.current;
    if (!element) return;
    const resize = () => {
      element.style.height = "auto";
      element.style.height = `${element.scrollHeight}px`;
    };
    resize();
    if (typeof ResizeObserver === "undefined" || !element.parentElement) return;
    let width = element.parentElement.clientWidth;
    const observer = new ResizeObserver((entries) => {
      const next = entries[0]?.contentRect.width;
      if (next !== undefined && next !== width) {
        width = next;
        resize();
      }
    });
    observer.observe(element.parentElement);
    return () => observer.disconnect();
  }, [draft]);
  return (
    <>
      <span className={(className ?? "") + " report-print-field"}>{value}</span>
      <textarea
        ref={field}
        id={id}
        className={`${className ?? ""} report-editable-field`}
        aria-label={label}
        value={draft}
        rows={1}
        maxLength={allowEmpty ? 4000 : 200}
        placeholder={allowEmpty ? "Add a caption…" : undefined}
        onFocus={() => {
          focused.current = true;
        }}
        onChange={(event) => setDraft(event.target.value)}
        onKeyDown={(event) => {
          if (event.key === "Enter" && !event.shiftKey) {
            event.preventDefault();
            event.currentTarget.blur();
          }
          if (event.key === "Escape") {
            discard.current = true;
            setDraft(value);
            event.currentTarget.blur();
          }
        }}
        onBlur={() => {
          focused.current = false;
          if (discard.current) {
            discard.current = false;
            return;
          }
          if (!allowEmpty && !draft.trim()) setDraft(value);
          else if (draft !== value) void onSave(draft.trim());
        }}
      />
    </>
  );
}
function ReportImage({ href, alt }: { href: string; alt: string }) {
  const [failed, setFailed] = useState(false),
    [attempt, setAttempt] = useState(0);
  return failed ? (
    <div className="report-image-error">
      <p>The image could not be loaded.</p>
      <button
        type="button"
        onClick={() => {
          setAttempt(attempt + 1);
          setFailed(false);
        }}
      >
        Reload image
      </button>
    </div>
  ) : (
    <img
      key={attempt}
      className="report-figure-image"
      src={resolveArtifactUrl(href)}
      alt={alt}
      onError={() => setFailed(true)}
    />
  );
}

import { useRef, useState } from "react";
import { createPortal } from "react-dom";
import { apiUrl } from "../../api/client";
import type { ReferenceImage } from "../../api/schemas/referenceImages";
import type { DraftReferenceImage } from "./useReferenceImages";
import "./referenceImages.css";

type Preview = { src: string; name: string };

export function ReferenceImages({
  images = [],
  drafts = [],
  onRemove,
  onRetry,
  disabled = false,
}: {
  images?: ReferenceImage[];
  drafts?: DraftReferenceImage[];
  onRemove?: (id: string) => void;
  onRetry?: (id: string) => void;
  disabled?: boolean;
}) {
  const dialog = useRef<HTMLDialogElement>(null);
  const [preview, setPreview] = useState<Preview | null>(null);
  function show(value: Preview) {
    setPreview(value);
    dialog.current?.showModal();
  }
  if (!images.length && !drafts.length) return null;
  return (
    <>
      <div className="reference-image-list" aria-label="Plot reference images">
        {images.map((image) => (
          <div className="reference-image-item" key={image.image_id}>
            <button
              type="button"
              className="reference-image-preview"
              aria-label={`View ${image.name}`}
              onClick={() =>
                show({ src: apiUrl(image.links.content), name: image.name })
              }
            >
              <img src={apiUrl(image.links.thumbnail)} alt={image.name} />
            </button>
            <span className="reference-image-name">{image.name}</span>
          </div>
        ))}
        {drafts.map((item) => (
          <div className="reference-image-item" key={item.id}>
            <button
              type="button"
              className="reference-image-preview"
              aria-label={`View ${item.file.name}`}
              onClick={() => show({ src: item.preview, name: item.file.name })}
            >
              <img src={item.preview} alt={item.file.name} />
            </button>
            <div className="reference-image-info">
              <span className="reference-image-name">
                {item.file.name || "Pasted image"}
              </span>
              <span className="reference-image-state" role="status">
                {item.status === "uploading"
                  ? "Uploading…"
                  : item.status === "failed"
                    ? "Upload failed"
                    : "Plot reference"}
              </span>
              {item.error ? (
                <span className="reference-image-error" role="alert">
                  {item.error}
                </span>
              ) : null}
              {item.status === "failed" ? (
                <button
                  type="button"
                  className="reference-image-retry"
                  disabled={disabled}
                  onClick={() => onRetry?.(item.id)}
                >
                  Retry
                </button>
              ) : null}
            </div>
            <button
              type="button"
              className="reference-image-remove"
              aria-label={`Remove ${item.file.name}`}
              disabled={disabled}
              onClick={() => onRemove?.(item.id)}
            >
              ×
            </button>
          </div>
        ))}
      </div>
      {createPortal(
        <dialog
          className="reference-image-dialog"
          ref={dialog}
          aria-label={
            preview ? `Image preview: ${preview.name}` : "Image preview"
          }
          onClose={() => setPreview(null)}
          onClick={(event) => {
            if (event.target === event.currentTarget) dialog.current?.close();
          }}
        >
          <header>
            <span>{preview?.name}</span>
            <button
              type="button"
              aria-label="Close image preview"
              onClick={() => dialog.current?.close()}
            >
              ×
            </button>
          </header>
          {preview ? <img src={preview.src} alt={preview.name} /> : null}
        </dialog>,
        document.body,
      )}
    </>
  );
}

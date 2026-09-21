import { useEffect, useRef, useState } from "react";
import type { ReferenceImage } from "../../api/schemas/referenceImages";

export type UploadReference = (
  file: File,
  signal: AbortSignal,
  requestId: string,
) => Promise<ReferenceImage>;

export type DraftReferenceImage = {
  id: string;
  file: File;
  preview: string;
  status: "uploading" | "ready" | "failed";
  controller: AbortController;
  image?: ReferenceImage;
  error?: string;
};

export function useReferenceImages(
  upload?: UploadReference,
  removeSaved?: (image: ReferenceImage) => Promise<void>,
  projectId?: string | null,
) {
  const [items, setItems] = useState<DraftReferenceImage[]>([]);
  const [error, setError] = useState<string | null>(null);
  const current = useRef<DraftReferenceImage[]>([]);
  const mounted = useRef(true);
  const scope = useRef(projectId);
  const operations = useRef({ upload, removeSaved });
  operations.current = { upload, removeSaved };

  function publish(next: DraftReferenceImage[]) {
    current.current = next;
    if (mounted.current) setItems(next);
  }
  function deleteSaved(image?: ReferenceImage) {
    if (image)
      void operations.current.removeSaved?.(image).catch(() => undefined);
  }
  function discard(item: DraftReferenceImage, retained = false) {
    item.controller.abort();
    URL.revokeObjectURL(item.preview);
    if (!retained) deleteSaved(item.image);
  }
  async function start(item: DraftReferenceImage) {
    try {
      const operation = operations.current.upload;
      if (!operation) throw new Error("Image uploads are unavailable.");
      const image = await operation(item.file, item.controller.signal, item.id);
      const latest = current.current.find((entry) => entry.id === item.id);
      if (
        !mounted.current ||
        !latest ||
        latest.controller !== item.controller
      ) {
        deleteSaved(image);
        return;
      }
      publish(
        current.current.map((entry) =>
          entry.id === item.id ? { ...entry, image, status: "ready" } : entry,
        ),
      );
    } catch (reason) {
      const latest = current.current.find((entry) => entry.id === item.id);
      if (!mounted.current || !latest || latest.controller !== item.controller)
        return;
      publish(
        current.current.map((entry) =>
          entry.id === item.id
            ? {
                ...entry,
                status: "failed",
                error:
                  reason instanceof Error
                    ? reason.message
                    : "Image upload failed.",
              }
            : entry,
        ),
      );
    }
  }
  function add(files: File[]) {
    setError(null);
    if (!files.length) return;
    if (
      files.some(
        (file) =>
          !["image/png", "image/jpeg", "image/webp"].includes(file.type) &&
          !(file.type === "" && /\.(png|jpe?g|webp)$/i.test(file.name)),
      )
    ) {
      setError(
        "Add PNG, JPEG, or WebP plot images here. Use Data for data files.",
      );
      return;
    }
    if (current.current.length + files.length > 3) {
      setError("Attach up to three plot images. Remove one to add another.");
      return;
    }
    if (files.some((file) => file.size > 10 * 1024 * 1024)) {
      setError("Choose reference images smaller than 10 MB each.");
      return;
    }
    const added: DraftReferenceImage[] = files.map((file) => ({
      id:
        globalThis.crypto?.randomUUID?.() ??
        `image-${Date.now()}-${Math.random().toString(36).slice(2)}`,
      file,
      preview: URL.createObjectURL(file),
      status: "uploading",
      controller: new AbortController(),
    }));
    publish([...current.current, ...added]);
    added.forEach((item) => void start(item));
  }
  function remove(id: string) {
    const item = current.current.find((entry) => entry.id === id);
    if (!item) return;
    publish(current.current.filter((entry) => entry.id !== id));
    discard(item);
    setError(null);
  }
  function retry(id: string) {
    const old = current.current.find((entry) => entry.id === id);
    if (!old || old.status !== "failed") return;
    const item: DraftReferenceImage = {
      ...old,
      controller: new AbortController(),
      status: "uploading",
      error: undefined,
    };
    publish(current.current.map((entry) => (entry.id === id ? item : entry)));
    void start(item);
  }
  function commit() {
    const accepted = current.current;
    publish([]);
    accepted.forEach((item) => discard(item, true));
    setError(null);
  }
  useEffect(() => {
    if (scope.current && projectId !== scope.current) {
      const previous = current.current;
      publish([]);
      previous.forEach((item) => discard(item));
      setError(null);
    }
    scope.current = projectId;
  }, [projectId]);
  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
      current.current.forEach((item) => discard(item));
      current.current = [];
    };
  }, []);

  return {
    items,
    error,
    add,
    remove,
    retry,
    commit,
    blocked: items.some((item) => item.status !== "ready"),
    ready: items.flatMap((item) => (item.image ? [item.image] : [])),
  };
}

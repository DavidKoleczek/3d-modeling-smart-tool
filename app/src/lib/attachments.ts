import {
  useCallback,
  useState,
  type ClipboardEvent,
  type DragEvent,
} from "react";

import { type ModelSummary, type Upload } from "@/lib/api";
import { describe } from "@/lib/errors";

// What one request's files may add up to: the server takes a third more, as they travel in base64.
const MAX_BYTES = 20 * 1024 * 1024;
const IMAGE = /^image\/(png|jpeg|gif|webp)$/;

/** A file to work from, read and ready to send, with a preview when it is an image. */
export type FileAttachment = {
  upload: Upload;
  preview: string | null;
  size: number;
};

export type Attachments = {
  files: FileAttachment[];
  models: string[];
  error: string | null;
  addFiles: (files: Iterable<File>) => Promise<void>;
  removeFile: (index: number) => void;
  addModel: (name: string) => void;
  removeModel: (name: string) => void;
  clear: () => void;
};

function readBase64(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result).split(",", 2)[1] ?? "");
    reader.onerror = () =>
      reject(reader.error ?? new Error(`Could not read ${file.name}.`));
    reader.readAsDataURL(file);
  });
}

/** The models a request can work from: those in the directory with a script to read. */
export function referable(models: ModelSummary[]): ModelSummary[] {
  return models.filter((model) => model.files.includes("model.py"));
}

/** The files and models a request is to work from, as the person adds them by picker, drop, paste, or menu. */
export function useAttachments(): Attachments {
  const [files, setFiles] = useState<FileAttachment[]>([]);
  const [models, setModels] = useState<string[]>([]);
  const [error, setError] = useState<string | null>(null);

  const addFiles = useCallback(
    async (added: Iterable<File>) => {
      const read: FileAttachment[] = [];
      const problems: string[] = [];
      let total = files.reduce((sum, file) => sum + file.size, 0);
      for (const file of added) {
        if (total + file.size > MAX_BYTES) {
          problems.push(
            `${file.name} would take the files past 20 MB together; attach a smaller copy.`,
          );
          continue;
        }
        total += file.size;
        try {
          const data = await readBase64(file);
          const preview = IMAGE.test(file.type)
            ? `data:${file.type};base64,${data}`
            : null;
          read.push({
            upload: { name: file.name || "pasted", data },
            preview,
            size: file.size,
          });
        } catch (cause) {
          problems.push(describe(cause));
        }
      }
      setFiles((current) => [...current, ...read]);
      setError(problems.length > 0 ? problems.join(" ") : null);
    },
    [files],
  );

  const removeFile = useCallback((index: number) => {
    setFiles((current) => current.filter((_, at) => at !== index));
  }, []);

  const addModel = useCallback((name: string) => {
    setModels((current) =>
      current.includes(name) ? current : [...current, name],
    );
  }, []);

  const removeModel = useCallback((name: string) => {
    setModels((current) => current.filter((model) => model !== name));
  }, []);

  const clear = useCallback(() => {
    setFiles([]);
    setModels([]);
    setError(null);
  }, []);

  return {
    files,
    models,
    error,
    addFiles,
    removeFile,
    addModel,
    removeModel,
    clear,
  };
}

/** Handlers that take files dropped or pasted onto an element; a paste of text alone is left to the field. */
export function takesFiles(addFiles: Attachments["addFiles"]): {
  onDragOver: (event: DragEvent) => void;
  onDrop: (event: DragEvent) => void;
  onPaste: (event: ClipboardEvent) => void;
} {
  return {
    onDragOver: (event) => {
      if (event.dataTransfer.types.includes("Files")) {
        event.preventDefault();
      }
    },
    onDrop: (event) => {
      if (event.dataTransfer.files.length > 0) {
        event.preventDefault();
        void addFiles(Array.from(event.dataTransfer.files));
      }
    },
    onPaste: (event) => {
      if (event.clipboardData.files.length > 0) {
        event.preventDefault();
        void addFiles(Array.from(event.clipboardData.files));
      }
    },
  };
}

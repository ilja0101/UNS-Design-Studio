import { FileImage, FileSpreadsheet, FileText, File as FileIcon, Loader2, X } from "lucide-react";
import { attachmentUrl, type Attachment } from "../../api";
import { cx } from "../../components/ui";

/** A file picked in the composer: uploading, uploaded (has `attachment`), or failed. */
export interface PendingAttachment {
  key: string;
  name: string;
  size: number;
  attachment?: Attachment;
  error?: string;
}

const MAX_IMAGE_DIM = 1600;

/** Downscale a big screenshot or P&ID before upload — it is going into a model's
 *  context, where pixels are tokens, and nothing in a UNS needs 4K. Everything
 *  that is not an image passes through untouched. */
export async function prepareForUpload(file: File): Promise<File> {
  if (!file.type.startsWith("image/") || file.type === "image/gif") return file;
  const url = URL.createObjectURL(file);
  try {
    const img = new Image();
    await new Promise<void>((resolve, reject) => {
      img.onload = () => resolve();
      img.onerror = () => reject(new Error(`could not decode ${file.name}`));
      img.src = url;
    });
    if (img.naturalWidth <= MAX_IMAGE_DIM && img.naturalHeight <= MAX_IMAGE_DIM) return file;
    const scale = MAX_IMAGE_DIM / Math.max(img.naturalWidth, img.naturalHeight);
    const canvas = document.createElement("canvas");
    canvas.width = Math.round(img.naturalWidth * scale);
    canvas.height = Math.round(img.naturalHeight * scale);
    canvas.getContext("2d")!.drawImage(img, 0, 0, canvas.width, canvas.height);
    const blob = await new Promise<Blob | null>((resolve) => canvas.toBlob(resolve, "image/png"));
    if (!blob) return file;
    const name = file.name.replace(/\.[^.]+$/, "") + ".png";
    return new File([blob], name, { type: "image/png" });
  } finally {
    URL.revokeObjectURL(url);
  }
}

export function formatSize(n: number): string {
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${Math.round(n / 1024)} kB`;
  return `${(n / (1024 * 1024)).toFixed(1)} MB`;
}

function KindIcon({ kind, className }: { kind: Attachment["kind"]; className?: string }) {
  const props = { size: 13, className };
  if (kind === "table") return <FileSpreadsheet {...props} />;
  if (kind === "image") return <FileImage {...props} />;
  if (kind === "text") return <FileText {...props} />;
  return <FileIcon {...props} />;
}

/** One attachment, as a chip: in the composer (removable, may be uploading) and
 *  on a sent message (opens the file). Images show a thumbnail. */
export function AttachmentChip({
  attachment,
  uploading,
  error,
  onRemove,
}: {
  attachment: Attachment;
  uploading?: boolean;
  error?: string;
  onRemove?: () => void;
}) {
  const detail = error
    ? error
    : uploading
      ? "uploading…"
      : attachment.sheets?.length
        ? `${attachment.sheets.reduce((n, s) => n + s.rows, 0)} rows · ${formatSize(attachment.size)}`
        : formatSize(attachment.size);
  const href = attachment.id && !uploading ? attachmentUrl(attachment.id) : undefined;
  const Tag = href ? "a" : "span";

  return (
    <span
      className={cx(
        "inline-flex max-w-[260px] items-center gap-1.5 rounded-lg border px-2 py-1 text-[11px]",
        error ? "border-err/40 bg-err-soft text-err" : "border-border bg-surface-2 text-fg",
      )}
      title={error ?? `${attachment.name} · ${detail}`}
    >
      {attachment.kind === "image" && href ? (
        <img src={href} alt="" className="h-6 w-6 shrink-0 rounded object-cover" />
      ) : uploading ? (
        <Loader2 size={13} className="shrink-0 animate-spin text-fg-muted" />
      ) : (
        <KindIcon kind={attachment.kind} className="shrink-0 text-fg-muted" />
      )}
      <Tag
        {...(href ? { href, target: "_blank", rel: "noreferrer" } : {})}
        className="min-w-0 truncate font-medium hover:underline"
      >
        {attachment.name}
      </Tag>
      <span className="shrink-0 text-fg-faint">{detail}</span>
      {onRemove && (
        <button
          onClick={onRemove}
          title="Remove"
          className="ml-0.5 grid h-4 w-4 shrink-0 place-items-center rounded text-fg-faint hover:text-err"
        >
          <X size={11} />
        </button>
      )}
    </span>
  );
}

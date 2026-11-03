/**
 * Documents the coach chat accepts besides photos: training plans usually come as PDF,
 * Word or Excel. The backend extracts the text (POST /v1/coach/upload-document); the
 * chat sends it back with the message.
 */
export const DOCUMENT_EXTENSIONS = ['pdf', 'docx', 'xlsx', 'xls', 'csv'] as const;
export type DocumentKind = (typeof DOCUMENT_EXTENSIONS)[number];

/** `accept` for the chat's file picker: photos plus the document types. */
export const CHAT_FILE_ACCEPT = ['image/*', ...DOCUMENT_EXTENSIONS.map((e) => `.${e}`)].join(',');

/** Same limits as the backend. */
export const MAX_DOCS_PER_MESSAGE = 3;
export const MAX_DOC_BYTES = 10 * 1024 * 1024;

export function fileExtension(name: string): string {
  const i = name.lastIndexOf('.');
  return i >= 0 ? name.slice(i + 1).toLowerCase() : '';
}

/** A document we can read (by extension; phones often send an empty or generic MIME type). */
export function isDocumentFile(file: { name: string }): boolean {
  return (DOCUMENT_EXTENSIONS as readonly string[]).includes(fileExtension(file.name));
}

export function isImageFile(file: { name: string; type?: string }): boolean {
  if (file.type?.startsWith('image/')) return true;
  return ['jpg', 'jpeg', 'png', 'webp', 'gif', 'heic', 'heif'].includes(fileExtension(file.name));
}

/** Short badge for a document chip: PDF, DOC, XLS, CSV. */
export function documentBadge(nameOrKind: string): string {
  const ext = nameOrKind.includes('.') ? fileExtension(nameOrKind) : nameOrKind.toLowerCase();
  if (ext === 'pdf') return 'PDF';
  if (ext === 'docx' || ext === 'doc') return 'DOC';
  if (ext === 'xlsx' || ext === 'xls') return 'XLS';
  if (ext === 'csv') return 'CSV';
  return 'FILE';
}

/**
 * Why a picked file can't be attached, or null when it can. `alreadyAttached` counts
 * documents already in the composer.
 */
export function documentProblem(file: { name: string; size: number }, alreadyAttached: number): string | null {
  const ext = fileExtension(file.name);
  if (ext === 'doc') return `${file.name}: old Word files (.doc) aren't supported. Save it as .docx or PDF.`;
  if (!isDocumentFile(file)) return `${file.name}: use a PDF, Word (.docx), Excel or CSV file.`;
  if (file.size > MAX_DOC_BYTES) return `${file.name} is over 10 MB.`;
  if (alreadyAttached >= MAX_DOCS_PER_MESSAGE) return `Up to ${MAX_DOCS_PER_MESSAGE} documents per message.`;
  return null;
}

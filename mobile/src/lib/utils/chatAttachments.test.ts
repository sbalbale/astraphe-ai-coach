import { describe, expect, it } from 'vitest';
import { CHAT_FILE_ACCEPT, documentBadge, documentProblem, isDocumentFile, isImageFile } from './chatAttachments';

describe('chat attachments', () => {
  it('accepts photos and the document types in the picker', () => {
    expect(CHAT_FILE_ACCEPT).toBe('image/*,.pdf,.docx,.xlsx,.xls,.csv');
  });

  it('recognises documents by extension, case-insensitively', () => {
    expect(isDocumentFile({ name: 'Plan.DOCX' })).toBe(true);
    expect(isDocumentFile({ name: 'block.xls' })).toBe(true);
    expect(isDocumentFile({ name: 'notes.txt' })).toBe(false);
    expect(isImageFile({ name: 'photo.HEIC', type: '' })).toBe(true);
    expect(isImageFile({ name: 'x', type: 'image/png' })).toBe(true);
  });

  it('labels chips', () => {
    expect(documentBadge('12 week plan.pdf')).toBe('PDF');
    expect(documentBadge('docx')).toBe('DOC');
    expect(documentBadge('Sheet.xlsx')).toBe('XLS');
    expect(documentBadge('file')).toBe('FILE');
  });

  it('explains why a file cannot be attached', () => {
    expect(documentProblem({ name: 'plan.pdf', size: 1000 }, 0)).toBeNull();
    expect(documentProblem({ name: 'old.doc', size: 1000 }, 0)).toMatch(/\.docx or PDF/);
    expect(documentProblem({ name: 'notes.txt', size: 1000 }, 0)).toMatch(/PDF, Word/);
    expect(documentProblem({ name: 'big.pdf', size: 11 * 1024 * 1024 }, 0)).toMatch(/10 MB/);
    expect(documentProblem({ name: 'four.pdf', size: 1000 }, 3)).toMatch(/Up to 3/);
  });
});

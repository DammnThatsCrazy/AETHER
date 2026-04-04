import { useEffect, useRef, type ReactNode } from 'react';
import { cn } from '@shiki/lib/utils';

interface ModalProps {
  readonly open: boolean;
  readonly onClose: () => void;
  readonly children: ReactNode;
  readonly className?: string;
}

export function Modal({ open, onClose, children, className }: ModalProps) {
  const dialogRef = useRef<HTMLDialogElement>(null);

  useEffect(() => {
    const dialog = dialogRef.current;
    if (!dialog) return;
    if (open && !dialog.open) dialog.showModal();
    else if (!open && dialog.open) dialog.close();
  }, [open]);

  useEffect(() => {
    const dialog = dialogRef.current;
    if (!dialog) return;
    const handler = () => onClose();
    dialog.addEventListener('close', handler);
    return () => dialog.removeEventListener('close', handler);
  }, [onClose]);

  return (
    <dialog
      ref={dialogRef}
      className={cn(
        'backdrop:bg-black/60 bg-surface-overlay border border-border-default rounded-lg p-0 max-w-2xl w-full text-text-primary',
        className,
      )}
      onClick={(e) => { if (e.target === dialogRef.current) onClose(); }}
      onKeyDown={(e) => { if (e.key === 'Escape') onClose(); }}
    >
      {open && children}
    </dialog>
  );
}

export function ModalHeader({ children, className }: { readonly children: ReactNode; readonly className?: string }) {
  return <div className={cn('px-6 py-4 border-b border-border-default', className)}>{children}</div>;
}

export function ModalBody({ children, className }: { readonly children: ReactNode; readonly className?: string }) {
  return <div className={cn('px-6 py-4', className)}>{children}</div>;
}

export function ModalFooter({ children, className }: { readonly children: ReactNode; readonly className?: string }) {
  return <div className={cn('px-6 py-4 border-t border-border-default flex justify-end gap-2', className)}>{children}</div>;
}

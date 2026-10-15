import { useState, type FC } from 'react';
import type { LifecycleState } from './notification-lifecycle-badge';

interface Props {
  readonly notificationId: string;
  readonly currentState: LifecycleState;
  readonly canApprove: boolean;
  readonly canSuppress: boolean;
  readonly canEscalate: boolean;
  readonly onApprove: (id: string, annotation?: string) => Promise<void>;
  readonly onSuppress: (id: string, annotation?: string) => Promise<void>;
  readonly onEscalate: (id: string, annotation?: string) => Promise<void>;
  readonly onAnnotate: (id: string, annotation: string) => Promise<void>;
}

type ActionType = 'approve' | 'suppress' | 'escalate' | 'annotate' | null;

const TERMINAL_STATES: LifecycleState[] = ['approved', 'propagated', 'suppressed', 'expired'];

export const OperatorActionBar: FC<Props> = ({
  notificationId,
  currentState,
  canApprove,
  canSuppress,
  canEscalate,
  onApprove,
  onSuppress,
  onEscalate,
  onAnnotate,
}) => {
  const [busy, setBusy] = useState<ActionType>(null);
  const [annotationMode, setAnnotationMode] = useState<ActionType>(null);
  const [annotationText, setAnnotationText] = useState('');

  const isTerminal = TERMINAL_STATES.includes(currentState);
  if (isTerminal) {
    return (
      <p className="text-xs text-zinc-500 italic">
        No further actions available ({currentState}).
      </p>
    );
  }

  const withAnnotation = (action: ActionType) => {
    setAnnotationMode(action);
    setAnnotationText('');
  };

  const handleConfirm = async () => {
    if (!annotationMode) return;
    const annotation = annotationText.trim() || undefined;
    setBusy(annotationMode);
    try {
      if (annotationMode === 'approve') await onApprove(notificationId, annotation);
      else if (annotationMode === 'suppress') await onSuppress(notificationId, annotation);
      else if (annotationMode === 'escalate') await onEscalate(notificationId, annotation);
      else if (annotationMode === 'annotate' && annotation) await onAnnotate(notificationId, annotation);
    } finally {
      setBusy(null);
      setAnnotationMode(null);
      setAnnotationText('');
    }
  };

  const handleCancel = () => {
    setAnnotationMode(null);
    setAnnotationText('');
  };

  if (annotationMode) {
    return (
      <div className="flex flex-col gap-2">
        <textarea
          value={annotationText}
          onChange={e => setAnnotationText(e.target.value)}
          placeholder={`Add a note for this ${annotationMode} action (optional)…`}
          className="w-full text-xs bg-zinc-800 border border-zinc-700 rounded px-3 py-2 text-zinc-200 placeholder-zinc-500 resize-none h-16 focus:outline-none focus:border-zinc-500"
          autoFocus
        />
        <div className="flex gap-2">
          <button
            onClick={() => void handleConfirm()}
            disabled={busy !== null}
            className="px-3 py-1 text-xs rounded bg-zinc-600 hover:bg-zinc-500 disabled:opacity-40 text-white font-medium"
          >
            {busy ? 'Processing…' : `Confirm ${annotationMode}`}
          </button>
          <button
            onClick={handleCancel}
            className="px-3 py-1 text-xs rounded bg-transparent border border-zinc-700 hover:border-zinc-500 text-zinc-400 hover:text-zinc-200"
          >
            Cancel
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="flex flex-wrap gap-2">
      {canApprove && (
        <button
          onClick={() => withAnnotation('approve')}
          disabled={busy !== null}
          className="px-3 py-1 text-xs rounded bg-green-700/40 hover:bg-green-700/60 border border-green-600/40 text-green-300 disabled:opacity-40 font-medium"
        >
          ✓ Approve
        </button>
      )}
      {canSuppress && (
        <button
          onClick={() => withAnnotation('suppress')}
          disabled={busy !== null}
          className="px-3 py-1 text-xs rounded bg-zinc-700/60 hover:bg-zinc-600/60 border border-zinc-600/40 text-zinc-300 disabled:opacity-40 font-medium"
        >
          ✗ Suppress
        </button>
      )}
      {canEscalate && (
        <button
          onClick={() => withAnnotation('escalate')}
          disabled={busy !== null}
          className="px-3 py-1 text-xs rounded bg-orange-700/40 hover:bg-orange-700/60 border border-orange-600/40 text-orange-300 disabled:opacity-40 font-medium"
        >
          ↑ Escalate
        </button>
      )}
      <button
        onClick={() => withAnnotation('annotate')}
        disabled={busy !== null}
        className="px-3 py-1 text-xs rounded bg-purple-700/40 hover:bg-purple-700/60 border border-purple-600/40 text-purple-300 disabled:opacity-40 font-medium"
      >
        ✎ Annotate
      </button>
    </div>
  );
};

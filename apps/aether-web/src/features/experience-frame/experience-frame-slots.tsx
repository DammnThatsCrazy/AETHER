/**
 * Per-slot state display for a governed 360 frame.
 *
 * Every state word, requirement, reason code, limitation, and policy disposition
 * is shown exactly as the server sent it. Partial, unknown, missing, and
 * degraded slots stay visibly different from available ones; nothing is
 * counted as success on the server's behalf, and slot content is not rendered.
 */

import { ErrorState, LoadingState } from '@aether/ui';
import { Badge, Card, CardContent, CardHeader, CardTitle } from '@aether/ui';
import type { ExperienceFrame, ExperienceFrameRequest, ExperienceFrameSlot } from './experience-frame-types';
import { useExperienceFrame } from './use-experience-frame';

type BadgeVariant = 'default' | 'success' | 'warning' | 'danger' | 'info';

/** Colour only; the label is always the raw server word. */
export function slotStateVariant(state: string): BadgeVariant {
  switch (state) {
    case 'available':
      return 'success';
    case 'degraded':
    case 'stale':
    case 'partial':
    case 'truncated':
    case 'conflicted':
    case 'unresolved':
      return 'warning';
    case 'missing':
    case 'unavailable':
    case 'suppressed':
      return 'danger';
    default:
      return 'default';
  }
}

function SlotRow({ slot }: { slot: ExperienceFrameSlot }) {
  const policy = slot.policyDisposition?.state;
  const notes = [
    ...slot.reasonCodes.map(code => `reason: ${code}`),
    ...slot.limitations.map(text => `limitation: ${text}`),
  ];
  return (
    <li className="py-2 border-b border-border-subtle last:border-b-0" data-slot-id={slot.id}>
      <div className="flex items-center justify-between gap-2">
        <span className="text-xs text-text-primary font-medium">{slot.id}</span>
        <span className="flex items-center gap-2">
          <span className="text-[10px] text-text-muted font-mono">{slot.requirement}</span>
          <Badge variant={slotStateVariant(slot.state)} size="sm" className="font-mono">
            {slot.state}
          </Badge>
        </span>
      </div>
      <div className="mt-1 flex flex-wrap gap-x-3 text-[10px] text-text-muted font-mono">
        <span>evidence refs: {slot.evidenceRefs.length}</span>
        {policy ? <span>policy: {policy}</span> : null}
      </div>
      {notes.length > 0 && (
        <ul className="mt-1 text-[10px] text-text-secondary">
          {notes.map(note => <li key={note}>{note}</li>)}
        </ul>
      )}
    </li>
  );
}

export interface ExperienceFrameSlotsProps {
  readonly frame: ExperienceFrame;
}

/** Pure over a validated frame, so it can be tested with a server-shaped fixture. */
export function ExperienceFrameSlots({ frame }: ExperienceFrameSlotsProps) {
  const degradation = frame.degradation?.level;
  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-sm">
          {frame.surfaceId} — {frame.subject.kind}:{frame.subject.id}
        </CardTitle>
      </CardHeader>
      <div className="flex flex-wrap gap-x-4 gap-y-1 px-4 py-2 border-b border-border-subtle bg-surface-overlay/40">
        <span className="text-[10px] text-text-muted font-mono">
          <span className="text-text-secondary">frame state:</span> {frame.state}
        </span>
        <span className="text-[10px] text-text-muted font-mono">
          <span className="text-text-secondary">generated:</span> {frame.generatedAt}
        </span>
        {frame.asOf ? (
          <span className="text-[10px] text-text-muted font-mono">
            <span className="text-text-secondary">as of:</span> {frame.asOf}
          </span>
        ) : null}
        {degradation && degradation !== 'none' ? (
          <span className="text-[10px] text-text-muted font-mono">
            <span className="text-text-secondary">degradation:</span> {degradation}
          </span>
        ) : null}
      </div>
      <CardContent className="pt-4">
        <ul aria-label={`${frame.surfaceId} slots`}>
          {frame.slots.map(slot => <SlotRow key={slot.id} slot={slot} />)}
        </ul>
        {frame.warnings.length > 0 && (
          <ul className="mt-2 text-[10px] text-text-muted">
            {frame.warnings.map(warning => <li key={warning}>warning: {warning}</li>)}
          </ul>
        )}
      </CardContent>
    </Card>
  );
}

export interface ExperienceFramePanelProps {
  readonly request: ExperienceFrameRequest;
}

/** Fetches and renders a frame; loading and error get their own honest states. */
export function ExperienceFramePanel({ request }: ExperienceFramePanelProps) {
  const { data, isLoading, error } = useExperienceFrame(request);
  if (isLoading) return <LoadingState lines={4} />;
  if (error) return <ErrorState title={`${request.surfaceId} unavailable`} message={error} />;
  if (!data) return null;
  return <ExperienceFrameSlots frame={data} />;
}

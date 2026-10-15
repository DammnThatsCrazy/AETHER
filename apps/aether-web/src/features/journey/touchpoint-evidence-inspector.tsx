import {
  Badge, Modal, ModalBody, ModalFooter, ModalHeader, Button,
} from '@aether/ui';
import {
  SOURCE_CLASS_DEFAULTS,
  canonicalSourceClass,
  type SourceClass,
} from '@aether/shared/traffic-source';
import { sourceClassLabel, humanizeRegistryValue } from '@aether-app/lib/traffic-source';

type Row = Record<string, unknown>;

// ── field access helpers ─────────────────────────────────────────────────────

function firstDefined(row: Row, keys: string[]): unknown {
  for (const key of keys) {
    const value = row[key];
    if (value !== null && value !== undefined && value !== '') return value;
  }
  return undefined;
}

function text(value: unknown, fallback = '—'): string {
  if (value === null || value === undefined || value === '') return fallback;
  return String(value);
}

function asArray(value: unknown): unknown[] {
  return Array.isArray(value) ? value : [];
}

function pct(value: unknown): string {
  if (value === null || value === undefined || !Number.isFinite(Number(value))) return '—';
  return `${Math.round(Number(value) * 100)}%`;
}

/** True when the row carries a positive machine-traffic signal. */
function isMachineTraffic(row: Row): boolean {
  const actor = String(firstDefined(row, ['actor_type']) ?? '').toLowerCase();
  return row.is_machine === true
    || row.suspected_machine_activity === true
    || row.machine_traffic === true
    || String(firstDefined(row, ['machine_traffic_state']) ?? '') === 'machine'
    || actor === 'machine' || actor === 'bot';
}

// ── row summary (for the trigger cell) ───────────────────────────────────────

function DetailRow({ label, children }: { readonly label: string; readonly children: React.ReactNode }) {
  return (
    <div className="flex items-start justify-between gap-4 py-1.5 border-b border-border-subtle last:border-0">
      <span className="text-xs text-text-secondary shrink-0">{label}</span>
      <span className="text-xs text-text-primary text-right break-words">{children}</span>
    </div>
  );
}

function Section({ title, children }: { readonly title: string; readonly children: React.ReactNode }) {
  return (
    <div className="space-y-1">
      <h4 className="text-[11px] font-medium text-text-secondary uppercase tracking-wide">{title}</h4>
      <div className="rounded-md border border-border-default bg-surface-raised px-3 py-1">{children}</div>
    </div>
  );
}

export interface TouchpointEvidenceInspectorProps {
  readonly touchpoint: Row | null;
  readonly open: boolean;
  readonly onClose: () => void;
  /** Whether this touchpoint is the first observed touch in the journey. */
  readonly isFirstTouch?: boolean;
  /** Whether this touchpoint is the most recent touch in the journey. */
  readonly isLatestTouch?: boolean;
}

/**
 * Evidence inspector (spec §15.2). Given a touchpoint row, presents the final
 * classification, evidence chain, campaign association, first/latest-touch
 * position, machine-traffic state, SDK/platform, and sanitization status.
 *
 * Labels come from the canonical shared traffic-source registry — legacy
 * "direct" renders "Direct / Unknown", never a typed-URL claim. Only fields the
 * API actually returns are shown; absent fields render "—". No values are
 * invented, and nothing beyond what the API returns is displayed (redaction is
 * the backend's responsibility; this view is render-only).
 */
export function TouchpointEvidenceInspector({
  touchpoint, open, onClose, isFirstTouch, isLatestTouch,
}: TouchpointEvidenceInspectorProps) {
  if (!touchpoint) return null;
  const tp = touchpoint;

  const rawSourceClass = firstDefined(tp, ['source_class']);
  const canonical = rawSourceClass !== undefined ? canonicalSourceClass(String(rawSourceClass)) : undefined;
  const defaults = canonical !== undefined ? SOURCE_CLASS_DEFAULTS[canonical as SourceClass] : undefined;

  const conflicts = asArray(firstDefined(tp, ['evidence_conflicts', 'classification_conflicts', 'conflicts']));
  const signals = asArray(firstDefined(tp, ['evidence_signals', 'evidence', 'signals']));

  const classifierVersion = firstDefined(tp, ['classifier_version', 'source_classifier_version']);
  const classificationRule = firstDefined(tp, ['classification_rule', 'winning_rule', 'classifier_rule']);
  const classificationConfidence = firstDefined(tp, ['classification_confidence', 'evidence_confidence']);
  const campaignResolution = firstDefined(tp, ['campaign_resolution_status', 'campaign_resolution']);
  const sanitization = firstDefined(tp, ['sanitization_status', 'sanitization', 'sanitized']);
  const platform = firstDefined(tp, ['platform', 'device_type']);
  const sdk = firstDefined(tp, ['sdk', 'sdk_name', 'sdk_id']);
  const proofLevel = firstDefined(tp, ['proof_level']);

  return (
    <Modal open={open} onClose={onClose} className="max-w-lg">
      <ModalHeader>
        <div className="flex items-center gap-2 flex-wrap">
          <h2 className="text-sm font-medium font-mono">Touchpoint evidence</h2>
          <Badge variant="default" size="sm">{sourceClassLabel(rawSourceClass)}</Badge>
          {isFirstTouch && <Badge variant="success" size="sm">First touch</Badge>}
          {isLatestTouch && <Badge variant="warning" size="sm">Latest touch</Badge>}
        </div>
      </ModalHeader>
      <ModalBody>
        <div className="space-y-4">
          <Section title="Classification">
            <DetailRow label="Final classification">{sourceClassLabel(rawSourceClass)}</DetailRow>
            {defaults && (
              <>
                <DetailRow label="Channel family"><Badge variant="default" size="sm">{humanizeRegistryValue(defaults.channelFamily)}</Badge></DetailRow>
                <DetailRow label="Economic class"><Badge variant="default" size="sm">{humanizeRegistryValue(defaults.economicClass)}</Badge></DetailRow>
              </>
            )}
            <DetailRow label="Source">{text(firstDefined(tp, ['source']))}</DetailRow>
            <DetailRow label="Medium">{text(firstDefined(tp, ['medium', 'referral_mediation_type']))}</DetailRow>
            <DetailRow label="Placement">{text(firstDefined(tp, ['placement', 'ad_placement']))}</DetailRow>
            <DetailRow label="Proof level">
              {proofLevel ? <Badge variant="default" size="sm">{humanizeRegistryValue(proofLevel)}</Badge> : '—'}
            </DetailRow>
            <DetailRow label="Classification confidence">{pct(classificationConfidence)}</DetailRow>
          </Section>

          <Section title="Winning rule">
            <DetailRow label="Rule">{text(classificationRule)}</DetailRow>
            <DetailRow label="Classifier version">{text(classifierVersion)}</DetailRow>
            <DetailRow label="Verification level">{text(firstDefined(tp, ['verification_level']))}</DetailRow>
            <DetailRow label="Entry method">{text(humanizeRegistryValue(firstDefined(tp, ['entry_method'])))}</DetailRow>
          </Section>

          <Section title="Evidence chain">
            <DetailRow label="Conflicts">
              {conflicts.length === 0
                ? <span className="text-text-muted">None</span>
                : (
                  <span className="flex flex-col items-end gap-1">
                    {conflicts.map((c, i) => (
                      <Badge key={i} variant="danger" size="sm">{typeof c === 'object' ? JSON.stringify(c) : String(c)}</Badge>
                    ))}
                  </span>
                )}
            </DetailRow>
            <DetailRow label="Signals">
              {signals.length === 0
                ? <span className="text-text-muted">None reported</span>
                : (
                  <span className="flex flex-col items-end gap-1">
                    {signals.map((sig, i) => {
                      const s = sig && typeof sig === 'object' && !Array.isArray(sig) ? sig as Row : {};
                      const label = typeof sig === 'object'
                        ? text(firstDefined(s, ['signal', 'type', 'name', 'kind']), JSON.stringify(sig))
                        : String(sig);
                      return <Badge key={i} variant="default" size="sm">{label}</Badge>;
                    })}
                  </span>
                )}
            </DetailRow>
          </Section>

          <Section title="Campaign">
            <DetailRow label="Campaign">{text(firstDefined(tp, ['campaign_id', 'campaign']))}</DetailRow>
            <DetailRow label="Resolution status">
              {campaignResolution ? <Badge variant="default" size="sm">{humanizeRegistryValue(campaignResolution)}</Badge> : '—'}
            </DetailRow>
          </Section>

          <Section title="Context">
            <DetailRow label="Journey position">
              {isFirstTouch && isLatestTouch ? 'Sole touch'
                : isFirstTouch ? 'Entry touch'
                : isLatestTouch ? 'Most recent touch'
                : 'Mid-journey'}
            </DetailRow>
            <DetailRow label="Journey role">{text(firstDefined(tp, ['journey_role']))}</DetailRow>
            <DetailRow label="Machine traffic">
              {isMachineTraffic(tp)
                ? <Badge variant="warning" size="sm">Machine-excluded</Badge>
                : <Badge variant="success" size="sm">Human-eligible</Badge>}
            </DetailRow>
            <DetailRow label="Platform">{text(platform)}</DetailRow>
            <DetailRow label="SDK">{text(sdk)}</DetailRow>
            <DetailRow label="Sanitization">
              {sanitization === undefined
                ? '—'
                : typeof sanitization === 'boolean'
                  ? <Badge variant={sanitization ? 'success' : 'default'} size="sm">{sanitization ? 'Sanitized' : 'Raw'}</Badge>
                  : <Badge variant="default" size="sm">{humanizeRegistryValue(sanitization)}</Badge>}
            </DetailRow>
          </Section>
        </div>
      </ModalBody>
      <ModalFooter>
        <Button variant="ghost" size="sm" onClick={onClose}>Close</Button>
      </ModalFooter>
    </Modal>
  );
}

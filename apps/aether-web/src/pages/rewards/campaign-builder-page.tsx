import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  Badge, Button, Card, CardContent, CardHeader, CardTitle, Input, Select,
} from '@aether/ui';
import { api } from '@aether-app/lib/api/endpoints';

// ── Types ─────────────────────────────────────────────────────────────────────

interface RewardRule {
  id: string; // local-only UUID for list key
  event_types: string;        // comma-separated
  min_attribution_weight: string;
  max_fraud_score: string;
  reward_amount: string;
  reward_unit: string;
  rail: string;
  execution_mode: string;
}

interface BasicsForm {
  name: string;
  description: string;
  reward_objective: string;
  start_time: string;
  end_time: string;
}

interface AttributionForm {
  attribution_model: string;
}

type Step = 'basics' | 'attribution' | 'rules' | 'review';

const STEPS: Step[] = ['basics', 'attribution', 'rules', 'review'];
const STEP_LABELS: Record<Step, string> = {
  basics: 'Basics',
  attribution: 'Attribution',
  rules: 'Rules',
  review: 'Review',
};

const ATTRIBUTION_MODELS = [
  { value: 'last_touch',     label: 'Last Touch — full credit to the last touchpoint' },
  { value: 'first_touch',    label: 'First Touch — full credit to the first touchpoint' },
  { value: 'linear',         label: 'Linear — equal credit across all touchpoints' },
  { value: 'time_decay',     label: 'Time Decay — more credit to recent touchpoints' },
  { value: 'position_based', label: 'Position Based — 40% first, 40% last, 20% middle' },
];

const RAILS = [
  'recommend_only',
  'manual_approval',
  'manual_export',
  'tenant_webhook',
  'onchain_claim',
  'stripe_credit',
  'loyalty_points',
  'coupon',
  'internal_credit',
  'x402_credit',
];

const EXECUTION_MODES = [
  { value: 'auto',   label: 'Auto — emit payload immediately on eligibility' },
  { value: 'batch',  label: 'Batch — accumulate and export in bulk' },
  { value: 'manual', label: 'Manual — hold for operator review' },
];

function nanoid(): string {
  return Math.random().toString(36).slice(2, 10);
}

function makeBlankRule(): RewardRule {
  return {
    id: nanoid(),
    event_types: '',
    min_attribution_weight: '0.1',
    max_fraud_score: '0.7',
    reward_amount: '',
    reward_unit: '',
    rail: 'manual_approval',
    execution_mode: 'auto',
  };
}

// ── Step progress bar ─────────────────────────────────────────────────────────

function StepProgress({ current }: { current: Step }) {
  const idx = STEPS.indexOf(current);
  return (
    <div className="flex items-center gap-2">
      {STEPS.map((step, i) => {
        const done = i < idx;
        const active = i === idx;
        return (
          <div key={step} className="flex items-center gap-2">
            <div className={[
              'w-6 h-6 rounded-full flex items-center justify-center text-xs font-semibold shrink-0',
              done  ? 'bg-success text-white' :
              active ? 'bg-accent text-white' :
                       'bg-surface-overlay text-text-muted',
            ].join(' ')}>
              {done ? '✓' : String(i + 1)}
            </div>
            <span className={`text-sm ${active ? 'font-semibold text-text-primary' : 'text-text-muted'}`}>
              {STEP_LABELS[step]}
            </span>
            {i < STEPS.length - 1 && (
              <div className={`h-px w-8 ${done ? 'bg-success' : 'bg-border-default'}`} />
            )}
          </div>
        );
      })}
    </div>
  );
}

// ── Step 1: Basics ────────────────────────────────────────────────────────────

function BasicsStep({
  form,
  onChange,
}: {
  form: BasicsForm;
  onChange: (f: BasicsForm) => void;
}) {
  function set(key: keyof BasicsForm, value: string) {
    onChange({ ...form, [key]: value });
  }

  return (
    <div className="space-y-4">
      <p className="text-xs text-text-muted">
        Campaigns define eligibility criteria. Tenant rails execute the rewards.
        Aether does not hold campaign budgets or execute payments.
      </p>

      <Input
        label="Campaign name *"
        value={form.name}
        onChange={e => set('name', e.target.value)}
        placeholder="e.g. Q3 Loyalty Boost"
      />

      <div className="space-y-1">
        <label className="block text-xs font-medium text-text-secondary">Description</label>
        <textarea
          className="w-full rounded-md border border-border-default bg-surface-base px-3 py-2 text-sm text-text-primary focus:outline-none focus:ring-1 focus:ring-accent resize-y min-h-[72px]"
          value={form.description}
          onChange={e => set('description', e.target.value)}
          placeholder="Describe the eligibility objective for this campaign…"
        />
      </div>

      <Input
        label="Reward objective"
        value={form.reward_objective}
        onChange={e => set('reward_objective', e.target.value)}
        placeholder="e.g. Increase repeat purchase rate, drive on-chain activity"
      />

      <div className="grid grid-cols-2 gap-4">
        <div className="space-y-1">
          <label className="block text-xs font-medium text-text-secondary">Start time</label>
          <input
            type="datetime-local"
            className="w-full rounded-md border border-border-default bg-surface-base px-3 py-2 text-sm text-text-primary focus:outline-none focus:ring-1 focus:ring-accent"
            value={form.start_time}
            onChange={e => set('start_time', e.target.value)}
          />
        </div>
        <div className="space-y-1">
          <label className="block text-xs font-medium text-text-secondary">End time (optional)</label>
          <input
            type="datetime-local"
            className="w-full rounded-md border border-border-default bg-surface-base px-3 py-2 text-sm text-text-primary focus:outline-none focus:ring-1 focus:ring-accent"
            value={form.end_time}
            onChange={e => set('end_time', e.target.value)}
          />
        </div>
      </div>
    </div>
  );
}

// ── Step 2: Attribution ───────────────────────────────────────────────────────

function AttributionStep({
  form,
  onChange,
}: {
  form: AttributionForm;
  onChange: (f: AttributionForm) => void;
}) {
  return (
    <div className="space-y-4">
      <p className="text-xs text-text-muted">
        Choose how credit is distributed across touchpoints when evaluating reward eligibility.
        Attribution weight is factored into each eligibility decision.
      </p>

      <Select
        label="Attribution model *"
        value={form.attribution_model}
        options={[{ value: '', label: 'Select model…' }, ...ATTRIBUTION_MODELS]}
        onChange={v => onChange({ attribution_model: v })}
      />

      {form.attribution_model && (
        <div className="rounded-md bg-surface-raised border border-border-default px-3 py-2 text-xs text-text-secondary space-y-1">
          <p className="font-medium text-text-primary">
            {ATTRIBUTION_MODELS.find(m => m.value === form.attribution_model)?.label}
          </p>
          <p className="text-text-muted">
            Attribution weight determines how much of a conversion event is credited to a specific touchpoint.
            Rules can filter on <code>min_attribution_weight</code> to ensure only high-confidence conversions
            trigger eligibility decisions.
          </p>
        </div>
      )}
    </div>
  );
}

// ── Step 3: Rules ─────────────────────────────────────────────────────────────

function RuleEditor({
  rule,
  index,
  onChange,
  onRemove,
}: {
  rule: RewardRule;
  index: number;
  onChange: (r: RewardRule) => void;
  onRemove: () => void;
}) {
  function set(key: keyof RewardRule, value: string) {
    onChange({ ...rule, [key]: value });
  }

  return (
    <div className="border border-border-default rounded-lg p-4 space-y-3">
      <div className="flex items-center justify-between">
        <span className="text-sm font-medium text-text-primary">Rule {index + 1}</span>
        <Button size="sm" variant="secondary" onClick={onRemove}
          className="border-danger text-danger hover:bg-danger/10 text-xs">
          Remove
        </Button>
      </div>

      <Input
        label="Event types (comma-separated) *"
        value={rule.event_types}
        onChange={e => set('event_types', e.target.value)}
        placeholder="e.g. purchase, wallet_connect, nft_mint"
      />

      <div className="grid grid-cols-2 gap-3">
        <Input
          label="Min attribution weight"
          type="number"
          value={rule.min_attribution_weight}
          onChange={e => set('min_attribution_weight', e.target.value)}
          placeholder="0.1"
        />
        <Input
          label="Max fraud score"
          type="number"
          value={rule.max_fraud_score}
          onChange={e => set('max_fraud_score', e.target.value)}
          placeholder="0.7"
        />
      </div>

      <div className="grid grid-cols-2 gap-3">
        <Input
          label="Reward amount *"
          type="number"
          value={rule.reward_amount}
          onChange={e => set('reward_amount', e.target.value)}
          placeholder="e.g. 10"
        />
        <Input
          label="Reward unit *"
          value={rule.reward_unit}
          onChange={e => set('reward_unit', e.target.value)}
          placeholder="e.g. USDC, points, %"
        />
      </div>

      <div className="grid grid-cols-2 gap-3">
        <Select
          label="Delivery rail *"
          value={rule.rail}
          options={RAILS.map(r => ({ value: r, label: r.replace(/_/g, ' ') }))}
          onChange={v => set('rail', v)}
        />

        <Select
          label="Execution mode"
          value={rule.execution_mode}
          options={EXECUTION_MODES}
          onChange={v => set('execution_mode', v)}
        />
      </div>
    </div>
  );
}

function RulesStep({
  rules,
  onChange,
}: {
  rules: RewardRule[];
  onChange: (rules: RewardRule[]) => void;
}) {
  function addRule() {
    onChange([...rules, makeBlankRule()]);
  }

  function updateRule(index: number, r: RewardRule) {
    const next = [...rules];
    next[index] = r;
    onChange(next);
  }

  function removeRule(index: number) {
    onChange(rules.filter((_, i) => i !== index));
  }

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <p className="text-xs text-text-muted">
          Each rule defines eligibility criteria and maps to a delivery rail.
          Multiple rules can match a single event — each produces an independent action payload.
        </p>
        <Button size="sm" variant="secondary" onClick={addRule}>
          + Add rule
        </Button>
      </div>

      {rules.length === 0 && (
        <div className="border border-dashed border-border-default rounded-lg px-4 py-8 text-center">
          <p className="text-sm text-text-muted">No rules yet.</p>
          <p className="text-xs text-text-muted mt-1">Add at least one rule to define eligibility criteria.</p>
          <Button size="sm" variant="secondary" className="mt-3" onClick={addRule}>
            Add first rule
          </Button>
        </div>
      )}

      <div className="space-y-3">
        {rules.map((rule, i) => (
          <RuleEditor
            key={rule.id}
            rule={rule}
            index={i}
            onChange={r => updateRule(i, r)}
            onRemove={() => removeRule(i)}
          />
        ))}
      </div>
    </div>
  );
}

// ── Step 4: Review ────────────────────────────────────────────────────────────

function ReviewStep({
  basics,
  attribution,
  rules,
}: {
  basics: BasicsForm;
  attribution: AttributionForm;
  rules: RewardRule[];
}) {
  return (
    <div className="space-y-4">
      <div className="rounded-md bg-surface-raised border border-border-default p-4 space-y-3">
        <h3 className="text-sm font-semibold text-text-primary">Campaign Basics</h3>
        <dl className="grid grid-cols-2 gap-x-4 gap-y-1.5 text-xs">
          <dt className="text-text-secondary">Name</dt>
          <dd className="text-text-primary font-medium">{basics.name || '—'}</dd>
          <dt className="text-text-secondary">Objective</dt>
          <dd className="text-text-primary">{basics.reward_objective || '—'}</dd>
          <dt className="text-text-secondary">Start</dt>
          <dd className="text-text-primary">{basics.start_time || '—'}</dd>
          <dt className="text-text-secondary">End</dt>
          <dd className="text-text-primary">{basics.end_time || 'No end date'}</dd>
        </dl>
        {basics.description && (
          <p className="text-xs text-text-muted italic border-t border-border-default pt-2">{basics.description}</p>
        )}
      </div>

      <div className="rounded-md bg-surface-raised border border-border-default p-4 space-y-2">
        <h3 className="text-sm font-semibold text-text-primary">Attribution</h3>
        <p className="text-xs text-text-secondary">
          Model: <span className="text-text-primary font-medium">{attribution.attribution_model.replace(/_/g, ' ') || '—'}</span>
        </p>
      </div>

      <div className="rounded-md bg-surface-raised border border-border-default p-4 space-y-3">
        <h3 className="text-sm font-semibold text-text-primary">Eligibility Rules ({rules.length})</h3>
        {rules.length === 0 && <p className="text-xs text-text-muted">No rules defined.</p>}
        {rules.map((r, i) => (
          <div key={r.id} className="border border-border-default rounded-md p-3 space-y-1.5">
            <p className="text-xs font-medium text-text-primary">Rule {i + 1}</p>
            <dl className="grid grid-cols-2 gap-x-4 gap-y-1 text-xs">
              <dt className="text-text-secondary">Event types</dt>
              <dd className="text-text-primary">{r.event_types || '—'}</dd>
              <dt className="text-text-secondary">Min attribution weight</dt>
              <dd className="text-text-primary">{r.min_attribution_weight}</dd>
              <dt className="text-text-secondary">Max fraud score</dt>
              <dd className="text-text-primary">{r.max_fraud_score}</dd>
              <dt className="text-text-secondary">Reward</dt>
              <dd className="text-text-primary font-semibold">{r.reward_amount} {r.reward_unit}</dd>
              <dt className="text-text-secondary">Rail</dt>
              <dd>
                <Badge variant="default" size="sm">{r.rail.replace(/_/g, ' ')}</Badge>
              </dd>
              <dt className="text-text-secondary">Execution</dt>
              <dd className="text-text-primary">{r.execution_mode}</dd>
            </dl>
          </div>
        ))}
      </div>

      <div className="rounded-md bg-surface-raised border border-border-default px-3 py-2">
        <p className="text-xs text-text-secondary">
          <strong className="text-text-primary">No-custody:</strong> This campaign defines eligibility criteria only.
          Tenant rails execute rewards. Aether does not hold or move campaign budgets.
        </p>
      </div>
    </div>
  );
}

// ── Page ──────────────────────────────────────────────────────────────────────

export function CampaignBuilderPage() {
  const navigate = useNavigate();
  const [step, setStep] = useState<Step>('basics');
  const [basics, setBasics] = useState<BasicsForm>({
    name: '',
    description: '',
    reward_objective: '',
    start_time: '',
    end_time: '',
  });
  const [attribution, setAttribution] = useState<AttributionForm>({
    attribution_model: 'last_touch',
  });
  const [rules, setRules] = useState<RewardRule[]>([makeBlankRule()]);
  const [submitting, setSubmitting] = useState(false);
  const [submitError, setSubmitError] = useState<string | null>(null);
  const [createdId, setCreatedId] = useState<string | null>(null);

  const currentIdx = STEPS.indexOf(step);
  const isFirst = currentIdx === 0;
  const isLast = step === 'review';

  function prev() {
    const prevStep = STEPS[currentIdx - 1];
    if (prevStep !== undefined) setStep(prevStep);
  }

  function next() {
    const nextStep = STEPS[currentIdx + 1];
    if (nextStep !== undefined) setStep(nextStep);
  }

  function canAdvanceBasics() {
    return basics.name.trim().length > 0;
  }

  function canAdvanceAttribution() {
    return attribution.attribution_model.length > 0;
  }

  function canAdvanceRules() {
    if (rules.length === 0) return false;
    return rules.every(r =>
      r.event_types.trim().length > 0 &&
      r.reward_amount.trim().length > 0 &&
      r.reward_unit.trim().length > 0
    );
  }

  function canAdvance(): boolean {
    if (step === 'basics') return canAdvanceBasics();
    if (step === 'attribution') return canAdvanceAttribution();
    if (step === 'rules') return canAdvanceRules();
    return true;
  }

  async function handleCreate() {
    setSubmitting(true);
    setSubmitError(null);
    try {
      const campaignBody: Record<string, unknown> = {
        name: basics.name.trim(),
        description: basics.description.trim() || undefined,
        reward_objective: basics.reward_objective.trim() || undefined,
        attribution_model: attribution.attribution_model,
        status: 'active',
      };
      if (basics.start_time) campaignBody['start_time'] = new Date(basics.start_time).toISOString();
      if (basics.end_time) campaignBody['end_time'] = new Date(basics.end_time).toISOString();

      const result = await api.rewards.createCampaign(campaignBody);
      const campaignId = String(
        (result as Record<string, unknown>)['id'] ??
        (result as Record<string, unknown>)['campaign_id'] ??
        ''
      );

      if (campaignId) {
        await Promise.all(
          rules.map(r =>
            api.rewards.createCampaignRule(campaignId, {
              event_types: r.event_types.split(',').map(s => s.trim()).filter(Boolean),
              min_attribution_weight: parseFloat(r.min_attribution_weight) || 0.1,
              max_fraud_score: parseFloat(r.max_fraud_score) || 0.7,
              reward_amount: parseFloat(r.reward_amount) || 0,
              reward_unit: r.reward_unit.trim(),
              rail: r.rail,
              execution_mode: r.execution_mode,
            })
          )
        );
        setCreatedId(campaignId);
      } else {
        setCreatedId('ok');
      }
    } catch (e) {
      setSubmitError(e instanceof Error ? e.message : 'Campaign creation failed');
    } finally {
      setSubmitting(false);
    }
  }

  // Success screen
  if (createdId) {
    return (
      <div className="p-8 max-w-lg mx-auto space-y-6">
        <Card>
          <CardContent className="pt-8 pb-8 text-center space-y-4">
            <div className="w-12 h-12 rounded-full bg-success/10 flex items-center justify-center mx-auto">
              <span className="text-success text-2xl">✓</span>
            </div>
            <h2 className="text-lg font-semibold text-text-primary">Campaign Created</h2>
            <p className="text-sm text-text-secondary">
              Campaign <strong>{basics.name}</strong> is now active.
              Aether will verify eligibility for incoming events — your configured rails will execute the rewards.
            </p>
            {createdId !== 'ok' && (
              <p className="text-xs text-text-muted font-mono">Campaign ID: {createdId}</p>
            )}
            <div className="flex items-center justify-center gap-3 pt-2">
              <Button size="sm" variant="secondary" onClick={() => navigate('/rewards/decisions')}>
                View Decisions
              </Button>
              <Button size="sm" onClick={() => navigate('/rewards/campaigns/new')}>
                New Campaign
              </Button>
            </div>
          </CardContent>
        </Card>
      </div>
    );
  }

  return (
    <div className="p-8 space-y-6 max-w-2xl mx-auto">
      {/* Header */}
      <div>
        <h1 className="text-xl font-semibold text-text-primary">New Reward Campaign</h1>
        <p className="text-sm text-text-secondary mt-0.5">
          Define eligibility criteria. Campaigns define when Aether verifies reward eligibility — tenant rails execute the rewards.
        </p>
      </div>

      {/* Progress */}
      <StepProgress current={step} />

      {/* Step content */}
      <Card>
        <CardHeader>
          <CardTitle>{STEP_LABELS[step]}</CardTitle>
        </CardHeader>
        <CardContent>
          {step === 'basics' && (
            <BasicsStep form={basics} onChange={setBasics} />
          )}
          {step === 'attribution' && (
            <AttributionStep form={attribution} onChange={setAttribution} />
          )}
          {step === 'rules' && (
            <RulesStep rules={rules} onChange={setRules} />
          )}
          {step === 'review' && (
            <ReviewStep basics={basics} attribution={attribution} rules={rules} />
          )}
        </CardContent>
      </Card>

      {/* Submit error */}
      {submitError && (
        <p className="text-xs text-danger border border-danger/30 rounded-md px-3 py-2 bg-surface-raised">
          {submitError}
        </p>
      )}

      {/* Navigation */}
      <div className="flex items-center justify-between">
        <Button
          variant="secondary"
          size="sm"
          onClick={prev}
          disabled={isFirst || submitting}
        >
          Back
        </Button>

        {isLast ? (
          <Button
            size="sm"
            onClick={() => { void handleCreate(); }}
            disabled={submitting}
          >
            {submitting ? 'Creating…' : 'Create Campaign'}
          </Button>
        ) : (
          <Button
            size="sm"
            onClick={next}
            disabled={!canAdvance()}
          >
            Next
          </Button>
        )}
      </div>
    </div>
  );
}

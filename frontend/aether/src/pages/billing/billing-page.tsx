import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  Badge,
  Button,
  Card,
  CardContent,
  CardHeader,
  CardTitle,
  ErrorState,
  GlyphIcon,
  LoadingState,
  Modal,
  ModalBody,
  ModalFooter,
  ModalHeader,
  Skeleton,
  StatusIndicator,
  TerminalSeparator,
  formatCount,
  formatCurrency,
  formatDate,
  useTimeContext,
  useToast,
} from '@aether/ui';
import {
  useBillingPlans,
  useCreateCheckout,
  useBillingPortal,
  useInvoices,
  useEnterpriseContact,
  useMeProfile,
} from '@aether-app/features/account';
import { env } from '@aether-app/lib/env';

const PLAN_ORDER = ['P1', 'P2', 'P3', 'P4'];

function PlanCard({
  plan,
  isCurrent,
  onUpgrade,
  loading,
}: {
  plan: { plan_id: string; display_name: string; price_monthly: number; monthly_quota: number; burst_rpm: number; features: string[] };
  isCurrent: boolean;
  onUpgrade: () => void;
  loading: boolean;
}) {
  const timeCtx = useTimeContext();
  const isHighTier = ['P3', 'P4'].includes(plan.plan_id);
  return (
    <Card className={isCurrent ? 'border-accent/50 bg-accent/5' : ''}>
      <CardHeader>
        <CardTitle className="flex items-center justify-between text-sm">
          <Badge variant={isHighTier ? 'accent' : 'default'} size="sm">{plan.display_name}</Badge>
          {isCurrent && <span className="text-xs text-accent font-mono">[current]</span>}
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-3">
        <div>
          <span className="text-xl font-mono text-accent">${plan.price_monthly}</span>
          <span className="text-xs text-text-muted">/mo</span>
        </div>
        <div className="text-xs font-mono text-text-secondary space-y-0.5">
          <div>{formatCount(plan.monthly_quota, timeCtx)} events/mo</div>
          <div>{formatCount(plan.burst_rpm, timeCtx)} req/min burst</div>
        </div>
        <ul className="space-y-1">
          {plan.features.map(f => (
            <li key={f} className="text-xs text-text-secondary flex items-center gap-1.5">
              <GlyphIcon glyph="[+]" className="text-success text-xs" />
              {f}
            </li>
          ))}
        </ul>
        {!isCurrent && (
          <Button variant="primary" size="sm" className="w-full" onClick={onUpgrade} disabled={loading}>
            {loading ? '[···]' : 'Upgrade'}
          </Button>
        )}
      </CardContent>
    </Card>
  );
}

interface EnterpriseModalProps {
  open: boolean;
  onClose: () => void;
  prefill: { name: string; email: string };
}

const COMPANY_TYPES = ['startup', 'smb', 'enterprise', 'agency', 'other'];
const MAX_MESSAGE = 500;

function EnterpriseContactModal({ open, onClose, prefill }: EnterpriseModalProps) {
  const { toast } = useToast();
  const { mutate, isLoading } = useEnterpriseContact();
  const [form, setForm] = useState({
    name: prefill.name,
    email: prefill.email,
    company_name: '',
    company_type: '',
    message: '',
  });
  const [success, setSuccess] = useState(false);
  const [submitError, setSubmitError] = useState<string | null>(null);

  function setField(field: string, value: string) {
    setForm(prev => ({ ...prev, [field]: value }));
    if (submitError) setSubmitError(null);
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setSubmitError(null);
    const result = await mutate(form);
    if (result !== null) {
      setSuccess(true);
      toast.success("Message sent — we'll be in touch within 2 business days");
    } else {
      setSubmitError('Could not send message — please try again');
      toast.error('Could not send message — please try again');
    }
  }

  const charCount = form.message.length;
  const charClass = charCount >= MAX_MESSAGE ? 'text-danger' : charCount >= 450 ? 'text-warning' : 'text-text-muted';

  return (
    <Modal open={open} onClose={onClose}>
      <ModalHeader>
        <h2 className="text-sm font-medium text-text-primary font-mono">Enterprise inquiry</h2>
      </ModalHeader>
      {success ? (
        <>
          <ModalBody className="space-y-3 text-center py-8">
            <div className="font-mono text-2xl text-success">[✓]</div>
            <p className="text-success font-mono text-xs">Message sent</p>
            <p className="text-text-secondary text-xs">Our team will respond within 2 business days.</p>
          </ModalBody>
          <ModalFooter>
            <Button variant="primary" size="sm" onClick={onClose}>Close</Button>
          </ModalFooter>
        </>
      ) : (
        <form onSubmit={(e) => { void handleSubmit(e); }}>
          <ModalBody className="space-y-3">
            <div className="grid grid-cols-2 gap-3">
              <div className="flex flex-col gap-1">
                <label htmlFor="ent-name" className="text-xs text-text-secondary">Name</label>
                <input id="ent-name" type="text" required value={form.name} onChange={e => setField('name', e.target.value)} className="bg-surface-raised text-text-primary border border-border-default rounded px-3 py-1.5 text-sm focus:outline-none focus:ring-1 focus:ring-border-focus" />
              </div>
              <div className="flex flex-col gap-1">
                <label htmlFor="ent-email" className="text-xs text-text-secondary">Email</label>
                <input id="ent-email" type="email" required value={form.email} onChange={e => setField('email', e.target.value)} className="bg-surface-raised text-text-primary border border-border-default rounded px-3 py-1.5 text-sm focus:outline-none focus:ring-1 focus:ring-border-focus" />
              </div>
            </div>
            <div className="flex flex-col gap-1">
              <label htmlFor="ent-company" className="text-xs text-text-secondary">Company</label>
              <input id="ent-company" type="text" required value={form.company_name} onChange={e => setField('company_name', e.target.value)} className="bg-surface-raised text-text-primary border border-border-default rounded px-3 py-1.5 text-sm focus:outline-none focus:ring-1 focus:ring-border-focus" />
            </div>
            <div className="flex flex-col gap-1">
              <label htmlFor="ent-type" className="text-xs text-text-secondary">Company type</label>
              <select id="ent-type" required value={form.company_type} onChange={e => setField('company_type', e.target.value)} className="bg-surface-raised text-text-primary border border-border-default rounded px-3 py-1.5 text-sm focus:outline-none focus:ring-1 focus:ring-border-focus">
                <option value="">Select…</option>
                {COMPANY_TYPES.map(t => (
                  <option key={t} value={t}>{t.charAt(0).toUpperCase() + t.slice(1)}</option>
                ))}
              </select>
            </div>
            <div className="flex flex-col gap-1">
              <div className="flex items-center justify-between">
                <label htmlFor="ent-message" className="text-xs text-text-secondary">Message</label>
                <span className={`text-xs font-mono ${charClass}`}>{charCount}/{MAX_MESSAGE}</span>
              </div>
              <textarea
                id="ent-message"
                required
                rows={4}
                maxLength={MAX_MESSAGE}
                value={form.message}
                onChange={e => setField('message', e.target.value)}
                placeholder="Tell us about your use case, scale, and requirements…"
                aria-label="Message"
                className="bg-surface-raised text-text-primary border border-border-default rounded px-3 py-1.5 text-sm focus:outline-none focus:ring-1 focus:ring-border-focus placeholder:text-text-muted resize-none"
              />
            </div>
          {submitError && (
            <p className="text-danger text-xs font-mono px-4 pb-2">{submitError}</p>
          )}
          </ModalBody>
          <ModalFooter>
            <Button variant="ghost" size="sm" type="button" onClick={onClose} disabled={isLoading}>Cancel</Button>
            <Button variant="primary" size="sm" type="submit" disabled={isLoading || !form.company_type || !form.message.trim()}>
              {isLoading ? '[···]' : 'Send message'}
            </Button>
          </ModalFooter>
        </form>
      )}
    </Modal>
  );
}

function EnterpriseCard({ onContact, disabled }: { onContact: () => void; disabled?: boolean }) {
  return (
    <Card className={disabled ? 'opacity-60' : 'border-accent/30'}>
      <CardHeader>
        <CardTitle className="flex items-center justify-between text-sm">
          <Badge variant="accent" size="sm">Protocol+</Badge>
          {disabled && <Badge variant="default" size="sm">Coming soon</Badge>}
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-3">
        <div>
          <span className="text-xl font-mono text-accent">Custom</span>
        </div>
        <div className="text-xs font-mono text-text-secondary space-y-0.5">
          <div>Custom event quota</div>
          <div>Custom rate limits</div>
        </div>
        <ul className="space-y-1">
          {['SLA guarantee', 'Dedicated support', 'Custom integrations', 'On-premise available'].map(f => (
            <li key={f} className="text-xs text-text-secondary flex items-center gap-1.5">
              <GlyphIcon glyph="[+]" className="text-success text-xs" />
              {f}
            </li>
          ))}
        </ul>
        <Button
          variant="secondary"
          size="sm"
          className="w-full"
          onClick={onContact}
          disabled={disabled}
          aria-label="Contact sales"
        >
          Contact sales
        </Button>
      </CardContent>
    </Card>
  );
}

export function BillingPage() {
  const navigate = useNavigate();
  const { toast } = useToast();
  const timeCtx = useTimeContext();
  const { data: plans, isLoading: plansLoading, error: plansError } = useBillingPlans();
  const { data: profile } = useMeProfile();
  const { data: invoices, isLoading: invoicesLoading, error: invoicesError } = useInvoices();
  const { mutate: createCheckout, isLoading: checkoutLoading } = useCreateCheckout();
  const { mutate: openPortal, isLoading: portalLoading } = useBillingPortal();
  const [enterpriseOpen, setEnterpriseOpen] = useState(false);
  const [checkoutingPlan, setCheckoutingPlan] = useState<string | null>(null);

  const enterpriseEmailVerified = env.VITE_ENTERPRISE_EMAIL_VERIFIED === 'true';

  async function handleUpgrade(planId: string) {
    setCheckoutingPlan(planId);
    const result = await createCheckout(planId);
    setCheckoutingPlan(null);
    if (!result?.url) {
      toast.error('Checkout unavailable — please try again or contact support');
      return;
    }
    window.location.href = result.url;
  }

  async function handlePortal() {
    const result = await openPortal(undefined);
    if (!result?.url) {
      toast.error('Billing portal unavailable — please try again');
      return;
    }
    window.location.href = result.url;
  }

  const currentPlanId = profile?.plan.plan_id ?? '';

  return (
    <div className="p-8 max-w-4xl">
      <div className="flex items-center justify-between mb-6">
        <span className="text-sm font-mono text-text-muted">Billing</span>
        <Button variant="ghost" size="sm" onClick={() => { void handlePortal(); }} disabled={portalLoading}>
          {portalLoading ? '[···]' : 'Manage billing →'}
        </Button>
      </div>

      <TerminalSeparator label="plans" className="mb-4" />

      {plansLoading && (
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
          {[1, 2, 3, 4].map(i => <Skeleton key={i} className="h-48" />)}
        </div>
      )}

      {plansError && <ErrorState message="Failed to load plans" />}

      {!plansLoading && plans && (
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
          {[...plans]
            .sort((a, b) => PLAN_ORDER.indexOf(a.plan_id) - PLAN_ORDER.indexOf(b.plan_id))
            .map(plan => (
              <PlanCard
                key={plan.plan_id}
                plan={plan}
                isCurrent={plan.plan_id === currentPlanId}
                onUpgrade={() => { void handleUpgrade(plan.plan_id); }}
                loading={checkoutLoading && checkoutingPlan === plan.plan_id}
              />
            ))}
          <EnterpriseCard
            onContact={() => setEnterpriseOpen(true)}
            disabled={!enterpriseEmailVerified}
          />
        </div>
      )}

      <TerminalSeparator label="invoices" className="my-6" />

      {invoicesLoading && <div className="space-y-2">{[1, 2, 3].map(i => <Skeleton key={i} className="h-8 w-full" />)}</div>}

      {invoicesError && <ErrorState message="Failed to load invoices" />}

      {!invoicesLoading && !invoicesError && invoices && invoices.length === 0 && (
        <p className="text-text-muted text-xs font-mono">No invoices yet.</p>
      )}

      {!invoicesLoading && !invoicesError && invoices && invoices.length > 0 && (
        <div className="space-y-1">
          {invoices.map(inv => (
            <div key={inv.id} className="flex items-center justify-between text-xs py-2 border-b border-border-subtle last:border-0">
              <span className="text-text-secondary font-mono">
                {formatDate(inv.period_start, timeCtx)}
              </span>
              <span className="text-text-primary font-mono">
                {formatCurrency(inv.amount / 100, inv.currency, timeCtx)}
              </span>
              <Badge
                variant={inv.status === 'paid' ? 'default' : 'default'}
                size="sm"
                className={inv.status === 'paid' ? 'text-success' : 'text-warning'}
              >
                {inv.status}
              </Badge>
              {inv.invoice_url && (
                <button
                  onClick={() => window.open(inv.invoice_url!, '_blank', 'noopener')}
                  className="text-accent underline"
                >
                  Download
                </button>
              )}
            </div>
          ))}
        </div>
      )}

      {enterpriseOpen && (
        <EnterpriseContactModal
          open
          onClose={() => setEnterpriseOpen(false)}
          prefill={{ name: profile?.name ?? '', email: profile?.contact_email ?? '' }}
        />
      )}
    </div>
  );
}

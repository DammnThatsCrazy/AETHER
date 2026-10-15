import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { Button, Card, CardContent, CardHeader, ErrorState } from '@aether/ui';
import { useMutation, queryCache } from '@aether/ui';
import { api } from '@aether-app/lib/api/endpoints';

const CHANNELS = ['paid_search', 'paid_social', 'email', 'push', 'sms', 'organic', 'referral', 'direct', 'affiliate', 'other'];

export function CustomCampaignPage() {
  const navigate = useNavigate();

  const [name, setName] = useState('');
  const [channel, setChannel] = useState('');
  const [startDate, setStartDate] = useState('');
  const [endDate, setEndDate] = useState('');
  const [error, setError] = useState<string | null>(null);

  const mutation = useMutation({
    mutationFn: (body: Record<string, unknown>) =>
      api.campaigns.create(body),
    onSuccess: (result) => {
      queryCache.invalidatePrefix('campaigns:');
      const id = (result as Record<string, unknown>)?.campaign_id as string | undefined;
      navigate(id ? `/campaigns/${id}` : '/campaign-intelligence/registry');
    },
    onError: (err: string) => {
      setError(err);
    },
  });

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!name.trim() || !channel) return;
    setError(null);
    mutation.mutate({
      name: name.trim(),
      channel,
      start_date: startDate || new Date().toISOString().slice(0, 10),
      end_date: endDate || undefined,
    });
  }

  return (
    <div className="p-8 max-w-lg mx-auto space-y-6">
      <div>
        <h1 className="text-xl font-semibold text-text-primary">New Custom Campaign</h1>
        <p className="text-sm text-text-secondary mt-0.5">
          Create a campaign not imported from an ad platform. Custom campaigns are labeled clearly
          throughout the registry and attribution views.
        </p>
      </div>

      {error && <ErrorState title="Failed to create campaign" message={error} />}

      <Card>
        <CardHeader>
          <span className="text-sm font-medium text-text-primary">Campaign details</span>
        </CardHeader>
        <CardContent>
          <form onSubmit={handleSubmit} className="space-y-4" noValidate>
            <div className="space-y-1.5">
              <label htmlFor="campaign-name" className="text-xs font-medium text-text-secondary">
                Campaign name <span aria-hidden>*</span>
              </label>
              <input
                id="campaign-name"
                type="text"
                required
                value={name}
                onChange={e => setName(e.target.value)}
                placeholder="Q3 Email Winback"
                className="w-full text-sm border border-border-default rounded px-3 py-2 bg-surface-raised text-text-primary focus:outline-none focus:ring-2 focus:ring-accent"
                aria-required="true"
              />
            </div>

            <div className="space-y-1.5">
              <label htmlFor="campaign-channel" className="text-xs font-medium text-text-secondary">
                Channel <span aria-hidden>*</span>
              </label>
              <select
                id="campaign-channel"
                value={channel}
                onChange={e => setChannel(e.target.value)}
                className="w-full text-sm border border-border-default rounded px-3 py-2 bg-surface-raised text-text-primary focus:outline-none focus:ring-2 focus:ring-accent"
              >
                <option value="">Select channel…</option>
                {CHANNELS.map(c => (
                  <option key={c} value={c}>{c.replace(/_/g, ' ')}</option>
                ))}
              </select>
            </div>

            <div className="grid grid-cols-2 gap-3">
              <div className="space-y-1.5">
                <label htmlFor="start-date" className="text-xs font-medium text-text-secondary">Start date</label>
                <input
                  id="start-date"
                  type="date"
                  value={startDate}
                  onChange={e => setStartDate(e.target.value)}
                  className="w-full text-sm border border-border-default rounded px-3 py-2 bg-surface-raised text-text-primary focus:outline-none focus:ring-2 focus:ring-accent"
                />
              </div>
              <div className="space-y-1.5">
                <label htmlFor="end-date" className="text-xs font-medium text-text-secondary">End date</label>
                <input
                  id="end-date"
                  type="date"
                  value={endDate}
                  onChange={e => setEndDate(e.target.value)}
                  className="w-full text-sm border border-border-default rounded px-3 py-2 bg-surface-raised text-text-primary focus:outline-none focus:ring-2 focus:ring-accent"
                />
              </div>
            </div>

            <div className="flex items-center justify-end gap-2 pt-2">
              <Button
                type="button"
                variant="ghost"
                size="sm"
                onClick={() => navigate(-1)}
              >
                Cancel
              </Button>
              <Button
                type="submit"
                variant="primary"
                size="sm"
                disabled={!name.trim() || !channel || mutation.isLoading}
              >
                {mutation.isLoading ? 'Creating…' : 'Create campaign'}
              </Button>
            </div>
          </form>
        </CardContent>
      </Card>

      <p className="text-xs text-text-muted">
        Custom campaigns appear in the registry with origin "Custom". They are not connected to any
        ad platform and do not sync spend data automatically. You can add UTM aliases after creation
        to link incoming traffic.
      </p>
    </div>
  );
}

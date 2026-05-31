import { GlyphIcon, TerminalSeparator } from '@aether/ui';
import { AetherLogo } from '@aether-app/components/aether-logo';

export function DataRetentionPage() {
  return (
    <div className="min-h-screen bg-surface-base px-4 py-12">
      <div className="max-w-2xl mx-auto">
        <AetherLogo size={32} className="mb-4" />
        <h1 className="text-lg font-medium text-text-primary mb-1">Data Retention Policy</h1>
        <p className="text-xs text-text-muted font-mono mb-8">Effective as of launch</p>

        <div className="bg-surface-raised border border-border-default rounded-lg p-6 space-y-6">
          <section className="space-y-2">
            <h2 className="text-sm font-medium text-text-primary flex items-center gap-2">
              <GlyphIcon glyph="[·]" className="text-accent" />
              Account deletion
            </h2>
            <p className="text-xs text-text-secondary leading-relaxed">
              When you delete your account, access is removed immediately and all API keys are
              revoked. Your event data, profile information, and configuration are retained for
              <strong className="text-text-primary"> 30 days</strong> for compliance and legal
              purposes. After 30 days, all data is permanently and irreversibly purged from all
              Aether systems, including backups.
            </p>
          </section>

          <TerminalSeparator />

          <section className="space-y-2">
            <h2 className="text-sm font-medium text-text-primary flex items-center gap-2">
              <GlyphIcon glyph="[·]" className="text-accent" />
              Active account data
            </h2>
            <p className="text-xs text-text-secondary leading-relaxed">
              For active accounts, event data is retained according to your plan tier. Raw events
              are stored for 90 days by default. Aggregated analytics data is retained indefinitely.
              Logs and audit trails are retained for 1 year.
            </p>
          </section>

          <TerminalSeparator />

          <section className="space-y-2">
            <h2 className="text-sm font-medium text-text-primary flex items-center gap-2">
              <GlyphIcon glyph="[·]" className="text-accent" />
              Your rights
            </h2>
            <p className="text-xs text-text-secondary leading-relaxed">
              You may request a full export of your data at any time from the account settings page.
              You may also submit a Data Subject Request (DSR) for access, portability, or deletion
              under applicable privacy regulations (GDPR, CCPA, etc.).
            </p>
          </section>

          <TerminalSeparator />

          <section className="space-y-2">
            <h2 className="text-sm font-medium text-text-primary flex items-center gap-2">
              <GlyphIcon glyph="[·]" className="text-accent" />
              Contact
            </h2>
            <p className="text-xs text-text-secondary">
              For data privacy inquiries:{' '}
              <a
                href="mailto:privacy@aether.dev"
                className="text-accent underline"
              >
                privacy@aether.dev
              </a>
            </p>
          </section>
        </div>
      </div>
    </div>
  );
}

import type { ReactNode } from 'react';
import { Eyebrow } from '@aether-app/components/ae-ui';

export function StepHeading({
  step,
  kicker,
  title,
  description,
  summary,
}: {
  readonly step: number;
  readonly kicker: string;
  readonly title: string;
  readonly description: ReactNode;
  readonly summary?: ReactNode;
}) {
  return (
    <div className="flex flex-col items-center gap-1.5 text-center">
      <Eyebrow>
        Step {step} of 4 · {kicker}
      </Eyebrow>
      <h1 className="text-[clamp(22px,4.6vw,28px)] font-medium tracking-[-0.56px]">{title}</h1>
      <p className="max-w-[520px] text-[14px] leading-normal" style={{ color: 'var(--ae-mute)' }}>
        {description}
      </p>
      {summary !== undefined && (
        <span className="ae-mono pt-0.5 text-[12px]" style={{ color: 'var(--ae-mute)' }} data-testid="onboarding-step-summary">
          {summary}
        </span>
      )}
    </div>
  );
}

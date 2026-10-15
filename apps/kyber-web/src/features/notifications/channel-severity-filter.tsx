import type { FC } from 'react';

export type SeverityLevel = 'P0' | 'P1' | 'P2' | 'P3' | 'info';

const ALL_SEVERITIES: SeverityLevel[] = ['P0', 'P1', 'P2', 'P3', 'info'];

const SEVERITY_LABEL: Record<SeverityLevel, string> = {
  P0:   'P0 — Critical',
  P1:   'P1 — High',
  P2:   'P2 — Medium',
  P3:   'P3 — Low',
  info: 'Info',
};

const SEVERITY_COLOR: Record<SeverityLevel, string> = {
  P0:   'text-red-400',
  P1:   'text-orange-400',
  P2:   'text-yellow-400',
  P3:   'text-blue-400',
  info: 'text-zinc-400',
};

interface Props {
  readonly value: readonly SeverityLevel[];
  readonly onChange: (next: SeverityLevel[]) => void;
  readonly className?: string;
}

export const ChannelSeverityFilter: FC<Props> = ({ value, onChange, className = '' }) => {
  const toggle = (sev: SeverityLevel) => {
    if (value.includes(sev)) {
      onChange(value.filter(s => s !== sev));
    } else {
      onChange([...value, sev]);
    }
  };

  return (
    <fieldset className={`flex flex-wrap gap-2 ${className}`}>
      <legend className="sr-only">Severity filter</legend>
      {ALL_SEVERITIES.map(sev => {
        const checked = value.includes(sev);
        return (
          <label
            key={sev}
            className={`flex items-center gap-1.5 px-3 py-1 rounded-full border text-xs font-medium cursor-pointer select-none transition-colors
              ${checked
                ? 'border-zinc-500 bg-zinc-700/60'
                : 'border-zinc-700 bg-transparent opacity-50 hover:opacity-75'
              }`}
          >
            <input
              type="checkbox"
              className="sr-only"
              checked={checked}
              onChange={() => toggle(sev)}
            />
            <span className={SEVERITY_COLOR[sev]}>{SEVERITY_LABEL[sev]}</span>
          </label>
        );
      })}
    </fieldset>
  );
};

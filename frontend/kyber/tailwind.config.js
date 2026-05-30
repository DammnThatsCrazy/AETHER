/** @type {import('tailwindcss').Config} */
export default {
  presets: [require('@aether/ui/tailwind.preset')],
  content: [
    './index.html',
    './src/**/*.{ts,tsx}',
    '../../frontend/shared/src/**/*.{ts,tsx}',
  ],
  darkMode: 'class',
  theme: {
    extend: {
      colors: {
        ctrl: {
          governance: 'var(--color-ctrl-governance)',
          char: 'var(--color-ctrl-char)',
          intake: 'var(--color-ctrl-intake)',
          noesis: 'var(--color-ctrl-noesis)',
          zeong: 'var(--color-ctrl-zeong)',
          triage: 'var(--color-ctrl-triage)',
          verification: 'var(--color-ctrl-verification)',
          commit: 'var(--color-ctrl-commit)',
          recovery: 'var(--color-ctrl-recovery)',
          chronicle: 'var(--color-ctrl-chronicle)',
          catalyst: 'var(--color-ctrl-catalyst)',
          relay: 'var(--color-ctrl-relay)',
        },
        chart: {
          1: 'var(--color-chart-1)',
          2: 'var(--color-chart-2)',
          3: 'var(--color-chart-3)',
          4: 'var(--color-chart-4)',
          5: 'var(--color-chart-5)',
          6: 'var(--color-chart-6)',
          7: 'var(--color-chart-7)',
          8: 'var(--color-chart-8)',
        },
        graph: {
          'trust-high': 'var(--color-graph-trust-high)',
          'trust-medium': 'var(--color-graph-trust-medium)',
          'trust-low': 'var(--color-graph-trust-low)',
          'risk-high': 'var(--color-graph-risk-high)',
          'risk-medium': 'var(--color-graph-risk-medium)',
          'risk-low': 'var(--color-graph-risk-low)',
          anomaly: 'var(--color-graph-anomaly)',
          selected: 'var(--color-graph-selected)',
          path: 'var(--color-graph-path)',
        },
      },
    },
  },
  plugins: [],
};

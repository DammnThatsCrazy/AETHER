/** @type {import('tailwindcss').Config} */
export default {
  presets: [require('@aether/ui/tailwind.preset')],
  content: [
    './index.html',
    './src/**/*.{ts,tsx}',
    '../../packages/ui/src/**/*.{ts,tsx}',
  ],
  darkMode: 'class',
  theme: {
    extend: {
      colors: {
        /* Stone palette */
        stone: {
          white:  '#f5f4f1',
          light:  '#eceae5',
          mid:    '#e2e0da',
          bone:   '#e8e6e1',
          ink:    '#1a1a1e',
        },
        graphite: '#1a1a1e',
        'deep-stone': '#111114',
        'deep-stone-dark': '#0d0d10',
        /* Accents */
        signal:  '#2563eb',
        steel:   '#6b8aa3',
        verdant: '#16a34a',
        amber:   '#d97706',
        ember:   '#dc2626',
        solar:   '#ca8a04',
        /* Surfaces via tokens */
        'surface-mid':     'var(--color-surface-mid)',
        'surface-sidebar': 'var(--color-surface-sidebar)',
        'border-hover':    'var(--color-border-hover)',
        'text-accent':     'var(--color-text-accent)',
        insight:           'var(--color-insight)',
      },
      fontFamily: {
        sans: ['Geist', 'Inter', 'system-ui', '-apple-system', 'sans-serif'],
        mono: ['GeistMono', 'JetBrains Mono', 'Fira Code', 'ui-monospace', 'monospace'],
      },
      fontSize: {
        '2xs': ['10px', { lineHeight: '1.2' }],
        display: ['56px', { lineHeight: '1.05', letterSpacing: '-0.03em' }],
        'hxl': ['40px', { lineHeight: '1.1', letterSpacing: '-0.02em' }],
        'hlg': ['28px', { lineHeight: '1.2', letterSpacing: '-0.02em' }],
        'h':   ['22px', { lineHeight: '1.3', letterSpacing: '-0.015em' }],
      },
      letterSpacing: {
        'eyebrow': '0.08em',
      },
      transitionDuration: {
        fast:   '120ms',
        medium: '200ms',
        slow:   '320ms',
      },
      transitionTimingFunction: {
        'out': 'cubic-bezier(0.22, 1, 0.36, 1)',
      },
      borderRadius: {
        DEFAULT: '4px',
        sm:  '3px',
        md:  '4px',
        lg:  '6px',
        xl:  '8px',
        pill: '999px',
      },
      width: {
        sidebar:  '220px',
        'sidebar-sm': '52px',
        panel:    '320px',
        'panel-lg': '400px',
      },
      minWidth: {
        sidebar: '220px',
      },
      maxWidth: {
        prose:   '680px',
        content: '1400px',
      },
      height: {
        topbar: '48px',
        row:    '36px',
        'row-sm': '28px',
      },
      boxShadow: {
        popover: '0 1px 2px rgba(0,0,0,0.1), 0 8px 24px rgba(0,0,0,0.2)',
        modal:   '0 8px 16px rgba(0,0,0,0.16), 0 24px 64px rgba(0,0,0,0.32)',
        'inset-focus': 'inset 0 0 0 1px #2563eb',
      },
      animation: {
        'pulse-live': 'pulse-live 1.4s ease-in-out infinite',
        'slide-in-right': 'slide-in-right 200ms cubic-bezier(0.22,1,0.36,1)',
        'fade-in': 'fade-in 200ms cubic-bezier(0.22,1,0.36,1)',
        'skeleton': 'skeleton 1.5s ease-in-out infinite',
      },
      keyframes: {
        'pulse-live': {
          '0%, 100%': { opacity: '1', transform: 'scale(1)' },
          '50%':       { opacity: '0.4', transform: 'scale(0.85)' },
        },
        'slide-in-right': {
          from: { opacity: '0', transform: 'translateX(8px)' },
          to:   { opacity: '1', transform: 'translateX(0)' },
        },
        'fade-in': {
          from: { opacity: '0' },
          to:   { opacity: '1' },
        },
        'skeleton': {
          '0%':   { backgroundPosition: '-200% 0' },
          '100%': { backgroundPosition: '200% 0' },
        },
      },
    },
  },
  plugins: [],
};

/**
 * Design tokens from the unified-site handoff (design/README.md, "Design
 * tokens"). Components use these names instead of hard-coded hex values.
 * Primary buttons are graphite (ink), never blue; accents carry color on
 * glyphs, chips, meters, status and links.
 *
 * @type {import('tailwindcss').Config}
 */
export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      colors: {
        stone: {
          50: '#f5f4f1', // page
          100: '#eceae5', // card
          200: '#e2e0da', // hover
        },
        line: {
          DEFAULT: '#d8d6d0',
          soft: '#e8e6e1',
          strong: '#c9c7c0',
        },
        raised: {
          DEFAULT: '#ffffff',
          warm: '#fbfaf8',
        },
        ink: '#1a1a1e',
        slate: '#6b6a65',
        ash: '#9c9b95',
        graphite: {
          body: '#4a4945', // body text on light surfaces (handoff: graphite-body)
          base: '#111114',
          raised: '#1a1a1e',
          hover: '#1f1f24',
          hairline: '#2a2a2f',
        },
        bone: '#e8e6e1', // text on dark
        cobalt: { DEFAULT: '#3a6896', ink: '#2d5373' },
        steel: { DEFAULT: '#5a85a8', ink: '#3f6a8c' },
        ochre: { DEFAULT: '#c9975a', ink: '#8a6433' },
        sage: { DEFAULT: '#6b9a7c', ink: '#4f8466' },
        ember: { DEFAULT: '#b5564a', ink: '#9c4439' },
      },
      fontFamily: {
        sans: ['Geist', 'system-ui', '-apple-system', 'sans-serif'],
        mono: ['"Geist Mono"', 'ui-monospace', 'monospace'],
      },
      fontSize: {
        display: ['64px', { lineHeight: '1.04', letterSpacing: '-1.92px', fontWeight: '500' }],
        'h-xl': ['40px', { lineHeight: '1.1', letterSpacing: '-0.8px', fontWeight: '500' }],
        'h-lg': ['28px', { lineHeight: '1.2', letterSpacing: '-0.56px', fontWeight: '500' }],
        h: ['22px', { lineHeight: '1.3', letterSpacing: '-0.33px', fontWeight: '500' }],
        body: ['14px', { lineHeight: '1.6' }],
        'body-sm': ['13px', { lineHeight: '1.55' }],
        caption: ['12px', { lineHeight: '1.5' }],
        label: ['11px', { lineHeight: '1.4', letterSpacing: '0.04em', fontWeight: '500' }],
      },
      borderRadius: {
        control: '6px',
        card: '12px',
        'card-lg': '16px',
        dialog: '18px',
      },
      boxShadow: {
        dialog: '0 24px 64px #1a1a1e2e',
        lift: '0 6px 18px #1a1a1e12',
      },
      maxWidth: {
        // Designs give 1200px of content plus 24px side padding (content-box).
        page: '1248px',
      },
      transitionTimingFunction: {
        site: 'cubic-bezier(0.22, 1, 0.36, 1)',
      },
      transitionDuration: {
        120: '120ms',
        200: '200ms',
        320: '320ms',
      },
    },
  },
  plugins: [],
};

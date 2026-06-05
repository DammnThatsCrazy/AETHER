/** @type {import('tailwindcss').Config} */
export default {
  presets: [require('@aether/ui/tailwind.preset')],
  content: [
    './index.html',
    './src/**/*.{ts,tsx}',
    '../../frontend/shared/src/**/*.{ts,tsx}',
  ],
  darkMode: 'class',
  theme: { extend: {} },
  plugins: [],
};

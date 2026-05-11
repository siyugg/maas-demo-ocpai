import type { Config } from 'tailwindcss'

export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      colors: {
        rh: {
          red: '#EE0000',
          darkred: '#BE0000',
          dark: '#151515',
          darker: '#0d0d0d',
          surface: '#1e1e1e',
          border: '#333333',
          muted: '#6b7280',
          text: '#e5e5e5',
        },
      },
      fontFamily: {
        sans: ['Red Hat Display', 'Red Hat Text', 'system-ui', 'sans-serif'],
        mono: ['Red Hat Mono', 'ui-monospace', 'monospace'],
      },
    },
  },
  plugins: [],
} satisfies Config

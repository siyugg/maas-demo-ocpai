import type { Config } from 'tailwindcss'

export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      colors: {
        rh: {
          red: 'rgb(var(--rh-red) / <alpha-value>)',
          darkred: 'rgb(var(--rh-darkred) / <alpha-value>)',
          dark: 'rgb(var(--rh-dark) / <alpha-value>)',
          darker: 'rgb(var(--rh-darker) / <alpha-value>)',
          surface: 'rgb(var(--rh-surface) / <alpha-value>)',
          border: 'rgb(var(--rh-border) / <alpha-value>)',
          muted: 'rgb(var(--rh-muted) / <alpha-value>)',
          text: 'rgb(var(--rh-text) / <alpha-value>)',
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

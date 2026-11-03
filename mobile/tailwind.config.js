import typography from '@tailwindcss/typography';

/**
 * Graphite + Sky theme (Nov 2026 UI overhaul).
 * Surfaces step up in lightness bg0 → bg3; `blue` is the brand accent (soft sky).
 * Keep in sync with the CSS custom properties in src/app.css.
 */

/** @type {import('tailwindcss').Config} */
export default {
  content: ['./src/**/*.{html,js,svelte,ts}'],
  theme: {
    extend: {
      colors: {
        bg0: '#0E0E10',
        bg1: '#141416',
        bg2: '#17171A',
        bg3: '#1F1F23',
        glass: 'rgba(255,255,255,0.03)',
        glass2: 'rgba(255,255,255,0.06)',
        border: '#26262B',
        blue: {
          DEFAULT: '#7FB4FF',
          dim: 'rgba(127,180,255,0.14)',
          glow: 'rgba(127,180,255,0.3)',
        },
        teal: {
          DEFAULT: '#00C8A8',
          dim: 'rgba(0,200,168,0.15)',
        },
        amber: {
          DEFAULT: '#FFCB88',
          dim: 'rgba(255,203,136,0.15)',
        },
        red: {
          DEFAULT: '#F07178',
          dim: 'rgba(240,113,120,0.15)',
        },
        sky: {
          DEFAULT: '#7FB4FF',
          dim: 'rgba(127,180,255,0.14)',
        },
        violet: {
          DEFAULT: '#B49CFF',
          dim: 'rgba(180,156,255,0.15)',
        },
        steel: {
          DEFAULT: '#6B7FA3',
          dim: 'rgba(107,127,163,0.15)',
        },
        green: {
          DEFAULT: '#6FCF97',
          dim: 'rgba(111,207,151,0.15)',
        },
        text0: '#EDEBE6',
        text1: '#A9A69E',
        text2: '#8A877F',
        astraphe: {
          neutral: '#EDEBE6',
          muted: '#A9A69E',
          teal: '#00C8A8',
          amber: '#FFCB88',
          red: '#F07178',
          blue: '#7FB4FF',
        },
        /** Training-load chart identities: fitness = accent, fatigue = neutral grey */
        chartCtl: '#7FB4FF',
        chartAtl: '#6A6A72',
      },
      fontFamily: {
        sans: ['Inter', 'system-ui', 'sans-serif'],
        mono: ['"JetBrains Mono"', 'ui-monospace', 'monospace'],
        display: ['"Instrument Serif"', 'Georgia', 'serif'],
      },
      borderRadius: {
        card: '24px',
      },
    }
  },
  plugins: [typography()]
};

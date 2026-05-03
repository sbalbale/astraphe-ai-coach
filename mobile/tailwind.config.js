/** @type {import('tailwindcss').Config} */
export default {
  content: ['./src/**/*.{html,js,svelte,ts}'],
  theme: {
    extend: {
      colors: {
        bg0: '#08080F',
        bg1: '#0F0F1A',
        bg2: '#141424',
        bg3: '#1C1C30',
        glass: 'rgba(255,255,255,0.04)',
        glass2: 'rgba(255,255,255,0.08)',
        border: 'rgba(255,255,255,0.07)',
        blue: {
          DEFAULT: '#4621FF',
          dim: 'rgba(70,33,255,0.15)',
          glow: 'rgba(70,33,255,0.3)',
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
        text0: '#F0F0FF',
        text1: 'rgba(240,240,255,0.65)',
        text2: 'rgba(240,240,255,0.35)',
        astrape: {
          neutral: '#F0F0FF',
          muted: 'rgba(240,240,255,0.65)',
          teal: '#00C8A8',
          amber: '#FFCB88',
          red: '#F07178',
          blue: '#4621FF',
        },
      },
      fontFamily: {
        sans: ['"Space Grotesk"', 'sans-serif'],
        mono: ['"Space Mono"', 'monospace'],
      }
    }
  },
  plugins: []
};

import { sveltekit } from '@sveltejs/kit/vite';
import { defineConfig } from 'vitest/config';

export default defineConfig({
  plugins: [sveltekit()],
  test: {
    include: ['src/**/*.{test,spec}.{js,ts}'],
    environment: 'jsdom',
    coverage: {
      provider: 'v8',
      reporter: ['text', 'html', 'json-summary'],
      include: ['src/lib/**/*.{ts,svelte}'],
      exclude: [
        'src/lib/components/**/*.svelte',
        'src/routes/**',
        'src/lib/**/*.d.ts',
        'src/app.html',
        'src/service-worker.ts',
        '**/*.test.ts',
        '**/*.config.ts'
      ],
      thresholds: {
        lines: 80,
        statements: 80,
        functions: 80,
        branches: 75
      }
    }
  }
});

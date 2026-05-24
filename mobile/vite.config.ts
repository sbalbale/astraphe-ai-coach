import { sveltekit } from '@sveltejs/kit/vite';
import { SvelteKitPWA } from '@vite-pwa/sveltekit';
import { defineConfig } from 'vite';

export default defineConfig({
	plugins: [
		sveltekit(),
		SvelteKitPWA({
			registerType: 'autoUpdate',
			injectRegister: null,
			strategies: 'injectManifest',
			srcDir: 'src',
			filename: 'service-worker.ts',
			manifest: {
				name: 'AstrapeAI',
				short_name: 'AstrapeAI',
				description: 'AI endurance coaching',
				start_url: '/dashboard',
				scope: '/',
				display: 'standalone',
				theme_color: '#08080F',
				background_color: '#08080F',
				icons: [
					{
						src: '/icons/icon-192.png',
						sizes: '192x192',
						type: 'image/png',
					},
					{
						src: '/icons/icon-512.png',
						sizes: '512x512',
						type: 'image/png',
					},
					{
						src: '/icons/icon-512-maskable.png',
						sizes: '512x512',
						type: 'image/png',
						purpose: 'maskable',
					},
				],
			},
			injectManifest: {
				globPatterns: ['client/**/*.{js,css,ico,png,svg,webp,woff,woff2}'],
			},
			workbox: {
				navigateFallback: '/index.html',
				navigateFallbackDenylist: [/^\/api\//],
			},
			devOptions: {
				enabled: true,
				type: 'module',
			},
		}),
	],
	server: {
		port: 5173,
		allowedHosts: ['924d-73-253-149-160.ngrok-free.app'],
	},
	// Pre-bundle Iconify so lazy route chunks don’t hit flaky "Outdated Optimize Dep" (504) after dep / lockfile changes.
	optimizeDeps: {
		include: ['@iconify/svelte', 'maplibre-gl'],
	},
	ssr: {
		noExternal: ['@iconify/svelte'],
	},
});

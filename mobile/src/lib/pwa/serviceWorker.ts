import { browser } from '$app/environment';
import { isStandaloneDisplayMode } from '$lib/utils/pwa';

/**
 * PWA service worker is for installed home-screen apps only.
 * In Safari tabs, a stale SW can cache broken assets and hang auth (black ASTRAPE screen).
 */
export async function setupPwaServiceWorker(): Promise<void> {
	if (!browser || !('serviceWorker' in navigator)) return;

	if (isStandaloneDisplayMode()) {
		const { registerSW } = await import('virtual:pwa-register');
		registerSW({ immediate: true });
		return;
	}

	// Regular browser (Safari tab): remove SW + Workbox caches from earlier deploys.
	const regs = await navigator.serviceWorker.getRegistrations();
	await Promise.all(regs.map((r) => r.unregister()));

	if ('caches' in window) {
		const keys = await caches.keys();
		await Promise.all(keys.map((k) => caches.delete(k)));
	}
}

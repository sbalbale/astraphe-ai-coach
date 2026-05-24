/// <reference lib="webworker" />
/// <reference types="vite-plugin-pwa/client" />

import { createHandlerBoundToURL, precacheAndRoute } from 'workbox-precaching';
import { NavigationRoute, registerRoute } from 'workbox-routing';

declare let self: ServiceWorkerGlobalScope;

precacheAndRoute(self.__WB_MANIFEST);

const navigationHandler = createHandlerBoundToURL('/index.html');
registerRoute(
	new NavigationRoute(navigationHandler, {
		denylist: [/^\/_/, /\/[^/?]+\.[^/]+$/],
	})
);

function resolveNotificationUrl(raw: string | undefined): string {
	const fallback = '/dashboard';
	if (!raw || typeof raw !== 'string') return fallback;
	try {
		const url = new URL(raw, self.location.origin);
		if (url.origin !== self.location.origin) return fallback;
		return `${url.pathname}${url.search}${url.hash}` || fallback;
	} catch {
		return fallback;
	}
}

async function focusOrOpenClient(targetUrl: string): Promise<void> {
	const clients = await self.clients.matchAll({ type: 'window', includeUncontrolled: true });
	for (const client of clients) {
		if (client.url.startsWith(self.location.origin)) {
			if ('navigate' in client && typeof client.navigate === 'function') {
				await client.navigate(targetUrl);
			}
			await client.focus();
			return;
		}
	}
	await self.clients.openWindow(targetUrl);
}

self.addEventListener('push', (event) => {
	let payload: { title?: string; body?: string; data?: { url?: string } } = {
		title: 'ASTRAPE',
		body: '',
		data: {},
	};
	try {
		payload = { ...payload, ...(event.data?.json() ?? {}) };
	} catch {
		/* ignore malformed payload */
	}

	event.waitUntil(
		self.registration.showNotification(payload.title ?? 'ASTRAPE', {
			body: payload.body ?? '',
			icon: '/astrape-logo.png',
			badge: '/icons/icon-192.png',
			data: payload.data ?? {},
		})
	);
});

self.addEventListener('notificationclick', (event) => {
	event.notification.close();
	const targetUrl = resolveNotificationUrl(
		(event.notification.data as { url?: string } | undefined)?.url
	);
	event.waitUntil(focusOrOpenClient(targetUrl));
});

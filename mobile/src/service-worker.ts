/// <reference lib="webworker" />
/// <reference types="vite-plugin-pwa/client" />

/**
 * Push-only service worker: shows push notifications and handles clicks on them.
 * It caches nothing. Offline precaching is what made Safari serve a stale app, which is
 * why registration was dropped (0697e23), and that also turned off web push.
 * The app registers this worker only to receive push (lib/services/pushNotifications).
 */
import {
	OPEN_CHAT_ACTION,
	chatIsOnScreen,
	coachThreadUrl,
	focusOrOpenClient,
	parseQuickReplies,
	replyActionId,
	replyIndexFromAction,
} from './lib/utils/coachThreads';

declare let self: ServiceWorkerGlobalScope;

// The PWA build (injectManifest) requires this injection point; the list isn't used.
void self.__WB_MANIFEST;

self.addEventListener('install', () => {
	self.skipWaiting();
});

self.addEventListener('activate', (event) => {
	// Take over pages right away, and delete the precache an older (caching) worker left
	// behind, so nobody keeps being served a stale copy of the app.
	event.waitUntil(
		(async () => {
			const keys = await caches.keys();
			await Promise.all(keys.map((k) => caches.delete(k)));
			await self.clients.claim();
		})()
	);
});

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

type PushData = {
	url?: string;
	type?: string;
	conversation_id?: string;
	/** JSON string (FCM data values are strings) or array of up to two quick replies. */
	quick_replies?: unknown;
};

self.addEventListener('push', (event) => {
	let payload: { title?: string; body?: string; data?: PushData } = {
		title: 'ASTRAPHE',
		body: '',
		data: {},
	};
	try {
		payload = { ...payload, ...(event.data?.json() ?? {}) };
	} catch {
		/* ignore malformed payload */
	}
	const data: PushData = payload.data ?? {};
	const replies = data.conversation_id ? parseQuickReplies(data.quick_replies, 2) : [];
	// Coach threads: one notification per thread (a newer one replaces it), and quick-reply
	// buttons where the platform supports actions (Chrome/Edge/Android; iOS ignores them).
	// With two replies both become buttons; with one, the other button opens the chat.
	const actions = replies.length >= 2
		? replies.map((r, i) => ({ action: replyActionId(i), title: r }))
		: replies.length === 1
			? [{ action: replyActionId(0), title: replies[0] }, { action: OPEN_CHAT_ACTION, title: 'Open chat' }]
			: [];
	const options: NotificationOptions & { actions?: { action: string; title: string }[]; renotify?: boolean } = {
		body: payload.body ?? '',
		icon: '/astraphe-logo.png',
		badge: '/android-chrome-192x192.png',
		data: { ...data, quick_replies: replies },
	};
	if (data.conversation_id) {
		options.tag = `coach-${data.conversation_id}`;
		options.renotify = true;
	}
	if (actions.length) options.actions = actions;
	const title = payload.title ?? 'ASTRAPHE';

	event.waitUntil(
		(async () => {
			// A coach reply while the chat is on screen: the athlete is watching it arrive.
			// Still show a notification (browsers penalise pushes that show none: Chrome posts
			// its own "updated in the background" one, Safari can drop the subscription), but
			// silently, under its own tag, and close it straight away.
			if (data.type === 'reply' && (await chatIsOnScreen(self.clients, self.location.origin))) {
				const tag = `onscreen-${Date.now()}`;
				await self.registration.showNotification(title, { ...options, tag, silent: true, renotify: false, actions: undefined });
				const shown = await self.registration.getNotifications({ tag });
				shown.forEach((n) => n.close());
				return;
			}
			await self.registration.showNotification(title, options);
		})()
	);
});

self.addEventListener('notificationclick', (event) => {
	event.notification.close();
	const data = (event.notification.data ?? {}) as PushData & { quick_replies?: string[] };
	// A quick-reply button opens the thread and sends that reply (the chat page reads ?reply=).
	const idx = replyIndexFromAction(event.action);
	const replies = Array.isArray(data.quick_replies) ? data.quick_replies : [];
	let target: string;
	if (data.conversation_id && idx !== null && replies[idx]) {
		target = coachThreadUrl(data.conversation_id, replies[idx]);
	} else if (data.conversation_id && event.action === OPEN_CHAT_ACTION) {
		target = coachThreadUrl(data.conversation_id);
	} else {
		target = data.url ?? (data.conversation_id ? coachThreadUrl(data.conversation_id) : undefined) ?? '';
	}
	event.waitUntil(focusOrOpenClient(self.clients, self.location.origin, resolveNotificationUrl(target)));
});

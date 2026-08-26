import { goto } from '$app/navigation';

/**
 * Client-side nav — avoids full document loads that break iOS PWA standalone.
 * `path` is dynamic (tab ids, hrefs from data), so — like the same-origin
 * link handler below — it goes straight to `goto()` rather than `resolve()`,
 * whose typed-route overloads only accept statically-known literal routes.
 */
export function navTo(path: string): void {
	void goto(path, { keepFocus: true, noScroll: true });
}

/** Catch any remaining same-origin <a href> (profile menu, etc.) on iOS PWA. */
export function installInAppLinkInterceptor(): () => void {
	if (typeof document === 'undefined') return () => {};

	const handler = (e: MouseEvent) => {
		if (e.defaultPrevented || e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) {
			return;
		}
		const anchor = (e.target as Element)?.closest?.('a[href]');
		if (!anchor || anchor.hasAttribute('download')) return;

		const href = anchor.getAttribute('href');
		if (
			!href ||
			href.startsWith('#') ||
			href.startsWith('/auth') ||
			href.startsWith('mailto:') ||
			href.startsWith('tel:') ||
			href.startsWith('javascript:')
		) {
			return;
		}

		let url: URL;
		try {
			url = new URL(href, location.href);
		} catch {
			return;
		}
		if (url.origin !== location.origin) return;

		e.preventDefault();
		void goto(url.pathname + url.search + url.hash, { keepFocus: true, noScroll: true });
	};

	document.addEventListener('click', handler, true);
	return () => document.removeEventListener('click', handler, true);
}

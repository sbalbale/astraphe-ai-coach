/** True when running as an installed PWA (iOS Add to Home Screen or install prompt). */
export function isStandaloneDisplayMode(): boolean {
	if (typeof window === 'undefined') return false;
	return (
		window.matchMedia('(display-mode: standalone)').matches ||
		// Legacy iOS Safari standalone flag
		(window.navigator as Navigator & { standalone?: boolean }).standalone === true
	);
}

/** Prefer same-window navigation in standalone; new tab in browser. */
export function externalLinkTargetAttr(): string {
	return isStandaloneDisplayMode() ? '' : ' target="_blank"';
}

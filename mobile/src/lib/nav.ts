import { goto } from '$app/navigation';
import { resolve } from '$app/paths';

/** Client-side nav — avoids full document loads that break iOS PWA standalone. */
export function navTo(path: string): void {
	void goto(resolve(path), { keepFocus: true, noScroll: true });
}

/**
 * Ensures Firebase only ships a single SPA shell. Per-route *.html files break iOS PWA
 * (full document loads → Safari chrome). Run after `vite build`.
 */
import { readdirSync, unlinkSync } from 'node:fs';
import { join } from 'node:path';

const buildDir = join(import.meta.dirname, '..', 'build');
let removed = 0;

for (const name of readdirSync(buildDir)) {
	if (name.endsWith('.html') && name !== 'index.html') {
		unlinkSync(join(buildDir, name));
		removed++;
		console.log(`[prune-spa-html] removed ${name}`);
	}
}

console.log(`[prune-spa-html] done (${removed} file(s) removed)`);

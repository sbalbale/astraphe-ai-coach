/**
 * Generates PWA / apple-touch PNGs and favicon.ico from static/astraphe-logo.svg
 * Run: pnpm icons
 */
import { readFileSync, writeFileSync, mkdirSync, copyFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { Resvg } from '@resvg/resvg-js';
import toIco from 'to-ico';

const __dirname = dirname(fileURLToPath(import.meta.url));
const root = join(__dirname, '..');
const staticDir = join(root, 'static');
const svgPath = join(staticDir, 'astraphe-logo.svg');
const iconsDir = join(staticDir, 'icons');

const svg = readFileSync(svgPath, 'utf8');

/** @returns {Buffer} */
function renderPngBuffer(size) {
	const resvg = new Resvg(svg, {
		fitTo: { mode: 'width', value: size },
		background: '#08080F',
	});
	return resvg.render().asPng();
}

function writePng(size, outPath) {
	writeFileSync(outPath, renderPngBuffer(size));
	console.log(`Wrote ${outPath} (${size}x${size})`);
}

mkdirSync(iconsDir, { recursive: true });

// Apple touch / notification icon (180px)
const appleTouchPath = join(staticDir, 'astraphe-logo.png');
writePng(180, appleTouchPath);

// Legacy filenames some platforms probe automatically
copyFileSync(appleTouchPath, join(staticDir, 'apple-touch-icon.png'));
copyFileSync(appleTouchPath, join(staticDir, 'apple-touch-icon-precomposed.png'));
console.log(`Wrote ${join(staticDir, 'apple-touch-icon.png')} (copy of astraphe-logo.png)`);
console.log(`Wrote ${join(staticDir, 'apple-touch-icon-precomposed.png')} (copy of astraphe-logo.png)`);

// PWA manifest icons
writePng(192, join(iconsDir, 'icon-192.png'));
writePng(512, join(iconsDir, 'icon-512.png'));
writePng(512, join(iconsDir, 'icon-512-maskable.png'));

// favicon.ico — ICO format maxes at 256px (directory entry is one byte per dimension)
const faviconIcoSizes = [16, 32, 48, 64, 128, 192, 256];
const ico = await toIco(faviconIcoSizes.map((size) => renderPngBuffer(size)));
const faviconPath = join(staticDir, 'favicon.ico');
writeFileSync(faviconPath, ico);
console.log(`Wrote ${faviconPath} (${faviconIcoSizes.join(', ')}px)`);

// Standalone PNG favicons for browsers that prefer larger icons (up to 512)
for (const size of [192, 512]) {
	writePng(size, join(iconsDir, `favicon-${size}.png`));
}

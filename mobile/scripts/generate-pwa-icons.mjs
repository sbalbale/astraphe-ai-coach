/**
 * Generates PWA / apple-touch PNGs from static/astraphe-logo.svg
 * Run: node scripts/generate-pwa-icons.mjs
 */
import { readFileSync, writeFileSync, mkdirSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { Resvg } from '@resvg/resvg-js';

const __dirname = dirname(fileURLToPath(import.meta.url));
const root = join(__dirname, '..');
const svgPath = join(root, 'static', 'astraphe-logo.svg');
const iconsDir = join(root, 'static', 'icons');

const svg = readFileSync(svgPath, 'utf8');

function renderPng(size, outPath) {
	const resvg = new Resvg(svg, {
		fitTo: { mode: 'width', value: size },
		background: '#08080F',
	});
	const png = resvg.render().asPng();
	writeFileSync(outPath, png);
	console.log(`Wrote ${outPath} (${size}x${size})`);
}

mkdirSync(iconsDir, { recursive: true });

renderPng(180, join(root, 'static', 'astraphe-logo.png'));
renderPng(192, join(iconsDir, 'icon-192.png'));
renderPng(512, join(iconsDir, 'icon-512.png'));
renderPng(512, join(iconsDir, 'icon-512-maskable.png'));

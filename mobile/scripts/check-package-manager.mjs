/**
 * Blocks accidental npm/yarn installs (cross-platform). Mirrors check-package-manager.sh.
 */
const ua = process.env.npm_config_user_agent ?? "";
if (!ua) process.exit(0);
if (ua.startsWith("pnpm")) process.exit(0);
console.error("");
console.error("❌  Wrong package manager detected.");
console.error("    This project uses pnpm. Run: pnpm install");
console.error("");
process.exit(1);

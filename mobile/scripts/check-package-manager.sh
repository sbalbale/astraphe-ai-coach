#!/bin/sh
if [ -z "$npm_config_user_agent" ]; then
  exit 0
fi
case "$npm_config_user_agent" in
  pnpm*) exit 0 ;;
  *)
    echo ""
    echo "❌  Wrong package manager detected."
    echo "    This project uses pnpm. Run: pnpm install"
    echo ""
    exit 1 ;;
esac

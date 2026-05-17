#!/bin/zsh
# Quick launcher cho Claude CLI ở project này — double-click trên Mac để mở.
# Hoặc gọi từ terminal: ./Run_Claude.command
#
# Auto: cd vào project root → start Claude CLI (sẽ tự load CLAUDE.md +
# .claude/settings.local.json với bypassPermissions mode).

set -e
PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$PROJECT_DIR"

echo "🚀 Khởi động Claude CLI tại: $PROJECT_DIR"
echo "   Mode: auto (bypassPermissions từ .claude/settings.local.json)"
echo "   Context: CLAUDE.md được auto-load"
echo ""

exec claude "$@"

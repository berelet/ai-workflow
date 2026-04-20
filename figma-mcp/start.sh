#!/bin/bash
# Запуск Figma MCP WebSocket сервера (socket relay)
export BUN_INSTALL="$HOME/.bun"
export PATH="$BUN_INSTALL/bin:$PATH"
exec bunx cursor-talk-to-figma-socket

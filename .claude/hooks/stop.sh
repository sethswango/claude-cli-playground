#!/bin/bash
# Completion notification hook for OpenClaw
INPUT=$(cat)
RESULT=$(echo "$INPUT" | jq -r '.stop_reason // "unknown"' 2>/dev/null)
echo "Claude CLI task completed (reason: $RESULT)" >&2
# Fire OpenClaw wake event
openclaw system event --text "Claude CLI task completed (stop_reason: $RESULT)" --mode now 2>/dev/null || true
exit 0

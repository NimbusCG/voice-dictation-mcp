#!/bin/bash
# Voice dictation hook for Claude Code UserPromptSubmit.
# Checks for new voice transcription and outputs it as context.
# If no new dictation, outputs nothing (silent).

# Auto-detect channel from tmux session name
CHANNEL="default"
if [ -n "$TMUX" ]; then
    SESSION=$(tmux display-message -p '#S' 2>/dev/null)
    if [ -n "$SESSION" ]; then
        CHANNEL="$SESSION"
    fi
fi

LATEST="$HOME/voice/transcripts/$CHANNEL/latest.txt"

# Check if file exists and has content
if [ -f "$LATEST" ]; then
    TEXT=$(cat "$LATEST" 2>/dev/null)
    if [ -n "$TEXT" ] && [ "${#TEXT}" -gt 1 ]; then
        echo "[Voice ($CHANNEL)]: $TEXT"
        # Consume — clear after reading
        echo -n > "$LATEST"
    fi
fi

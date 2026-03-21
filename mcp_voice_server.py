#!/usr/bin/env python3
"""
MCP Voice Dictation Server for Claude Code (Channel-aware).

Each Claude Code session can listen on a specific channel.
Channels map to subfolders in ~/voice/incoming/ and ~/voice/transcripts/.

Usage:
    python3 mcp_voice_server.py                    # default channel
    python3 mcp_voice_server.py --channel platform  # platform channel
    python3 mcp_voice_server.py --channel crm       # crm channel

On Windows, record to the matching subfolder:
    V:\\platform\\voice_20260321.wav  → picked up by --channel platform
    V:\\crm\\voice_20260321.wav      → picked up by --channel crm
"""

import json
import os
import sys
from datetime import datetime
from pathlib import Path

# Parse --channel argument
CHANNEL = "default"
for i, arg in enumerate(sys.argv[1:], 1):
    if arg == "--channel" and i < len(sys.argv) - 1:
        CHANNEL = sys.argv[i + 1]
        break

VOICE_DIR = Path.home() / "voice"
TRANSCRIPTS_DIR = VOICE_DIR / "transcripts" / CHANNEL
LATEST_FILE = TRANSCRIPTS_DIR / "latest.txt"
HISTORY_FILE = TRANSCRIPTS_DIR / "history.log"
GLOBAL_HISTORY = VOICE_DIR / "transcripts" / "history.log"

# Ensure dirs exist
TRANSCRIPTS_DIR.mkdir(parents=True, exist_ok=True)
(VOICE_DIR / "incoming" / CHANNEL).mkdir(parents=True, exist_ok=True)


def read_latest_transcript():
    """Read the most recent transcription for this channel."""
    if not LATEST_FILE.exists():
        return None, f"No dictation on channel '{CHANNEL}'. Record to ~/voice/incoming/{CHANNEL}/"

    text = LATEST_FILE.read_text().strip()
    if not text:
        return None, f"No new dictation on channel '{CHANNEL}'."

    mtime = datetime.fromtimestamp(LATEST_FILE.stat().st_mtime)
    age_seconds = (datetime.now() - mtime).total_seconds()

    if age_seconds > 3600:
        age_str = f"{int(age_seconds / 3600)}h {int((age_seconds % 3600) / 60)}m ago"
    elif age_seconds > 60:
        age_str = f"{int(age_seconds / 60)}m ago"
    else:
        age_str = f"{int(age_seconds)}s ago"

    return text, age_str


def read_history(count=10, channel_only=True):
    """Read recent transcription history."""
    hist_file = HISTORY_FILE if channel_only else GLOBAL_HISTORY
    if not hist_file.exists():
        return []

    lines = hist_file.read_text().strip().split("\n")
    entries = []
    for line in lines[-count:]:
        parts = line.split("|", 3)
        if len(parts) == 4:
            entries.append({
                "timestamp": parts[0],
                "channel": parts[1],
                "file": parts[2],
                "text": parts[3]
            })
    return entries


def handle_request(request):
    """Handle a JSON-RPC request."""
    method = request.get("method", "")
    req_id = request.get("id")

    if method == "initialize":
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {
                "protocolVersion": "2024-11-05",
                "capabilities": {"tools": {"listChanged": False}},
                "serverInfo": {
                    "name": f"voice-dictation-{CHANNEL}",
                    "version": "2.0.0"
                }
            }
        }

    elif method == "notifications/initialized":
        return None

    elif method == "tools/list":
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {
                "tools": [
                    {
                        "name": "dictate",
                        "description": (
                            f"Get the latest voice dictation on channel '{CHANNEL}'. "
                            "Use when the user says 'dictate', 'voice', or 'listen'. "
                            "Peeks without consuming — safe for multi-session use. "
                            "Treat the user's spoken text as their message to you."
                        ),
                        "inputSchema": {
                            "type": "object",
                            "properties": {
                                "consume": {
                                    "type": "boolean",
                                    "description": "Clear after reading so other sessions won't see it. Default: false."
                                }
                            }
                        }
                    },
                    {
                        "name": "accept_dictation",
                        "description": (
                            f"Consume the current dictation on channel '{CHANNEL}' "
                            "so other sessions won't pick it up."
                        ),
                        "inputSchema": {
                            "type": "object",
                            "properties": {}
                        }
                    },
                    {
                        "name": "dictation_history",
                        "description": (
                            "Show recent dictation history. "
                            "Use all_channels=true to see dictations across all channels."
                        ),
                        "inputSchema": {
                            "type": "object",
                            "properties": {
                                "count": {
                                    "type": "integer",
                                    "description": "Number of entries. Default: 5."
                                },
                                "all_channels": {
                                    "type": "boolean",
                                    "description": "Show history from all channels, not just this one. Default: false."
                                }
                            }
                        }
                    }
                ]
            }
        }

    elif method == "tools/call":
        tool_name = request.get("params", {}).get("name", "")
        arguments = request.get("params", {}).get("arguments", {})

        if tool_name == "dictate":
            text, age_or_error = read_latest_transcript()
            if text:
                result_text = f"[Channel: {CHANNEL} | {age_or_error}]: {text}"

                if arguments.get("consume") and LATEST_FILE.exists():
                    LATEST_FILE.write_text("")
                    result_text += "\n\n[Consumed — cleared from this channel.]"

                return {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "result": {
                        "content": [{"type": "text", "text": result_text}]
                    }
                }
            else:
                return {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "result": {
                        "content": [{"type": "text", "text": age_or_error}],
                        "isError": True
                    }
                }

        elif tool_name == "accept_dictation":
            if LATEST_FILE.exists():
                text = LATEST_FILE.read_text().strip()
                LATEST_FILE.write_text("")
                if text:
                    preview = text[:80] + ('...' if len(text) > 80 else '')
                    return {
                        "jsonrpc": "2.0",
                        "id": req_id,
                        "result": {
                            "content": [{"type": "text", "text": f"Consumed from [{CHANNEL}]: \"{preview}\""}]
                        }
                    }
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {
                    "content": [{"type": "text", "text": f"No dictation on channel '{CHANNEL}'."}]
                }
            }

        elif tool_name == "dictation_history":
            count = arguments.get("count", 5)
            all_ch = arguments.get("all_channels", False)
            history = read_history(count, channel_only=not all_ch)
            if history:
                label = "all channels" if all_ch else f"channel '{CHANNEL}'"
                result_text = f"Last {len(history)} dictation(s) ({label}):\n"
                for i, entry in enumerate(reversed(history), 1):
                    ch_tag = f"[{entry['channel']}] " if all_ch else ""
                    result_text += f"\n{i}. {ch_tag}[{entry['timestamp']}] {entry['text']}"
                return {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "result": {
                        "content": [{"type": "text", "text": result_text}]
                    }
                }
            else:
                return {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "result": {
                        "content": [{"type": "text", "text": "No dictation history."}],
                        "isError": True
                    }
                }

    return {
        "jsonrpc": "2.0",
        "id": req_id,
        "error": {"code": -32601, "message": f"Method not found: {method}"}
    }


def main():
    """Run the MCP server over stdio."""
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue

        try:
            request = json.loads(line)
        except json.JSONDecodeError:
            continue

        response = handle_request(request)
        if response is not None:
            sys.stdout.write(json.dumps(response) + "\n")
            sys.stdout.flush()


if __name__ == "__main__":
    main()

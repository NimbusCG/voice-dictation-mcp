# Voice Dictation for Claude Code

Voice input for Claude Code running on remote servers over SSH/tmux.

Record audio on your local machine → auto-transcribed by Whisper on the server → Claude Code reads it via MCP tool.

## Architecture

```
[Local machine]                              [Remote server]
voice_recorder.py                            ~/voice/
  records audio ──→ V:\ (SSHFS mount) ──→    incoming/{channel}/
                                                ↓ inotifywait
                                                ↓ faster-whisper
                                              transcripts/{channel}/latest.txt
                                                ↑
  "dictate" in Claude Code ←── MCP tool ──→   mcp_voice_server.py
```

## Components

| File | Where | Purpose |
|------|-------|---------|
| `voice_recorder.py` | Local (Windows/Mac/Linux) | Records audio, saves to mounted drive |
| `mcp_voice_server.py` | Remote server | MCP server exposing `dictate` tool to Claude Code |
| `transcribe_watcher.sh` | Remote server | Watches for new audio, transcribes with Whisper |
| `voice-watcher.service` | Remote server | systemd service for the watcher |

## Channels

Multiple users or sessions can use separate channels (subfolders):

```bash
# Recorder
python voice_recorder.py --channel platform
python voice_recorder.py --channel crm

# MCP config (per-project settings.json)
"args": ["mcp_voice_server.py", "--channel", "platform"]
```

Switch channels mid-session by typing `ch <name>` in the recorder.

## Setup

### Remote server

```bash
# Install dependencies
python3 -m venv ~/voice/venv
source ~/voice/venv/bin/activate
pip install faster-whisper
sudo apt install ffmpeg inotify-tools

# Install and start watcher service
sudo cp voice-watcher.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now voice-watcher

# Add MCP server to Claude Code settings (~/.claude/settings.json)
# "mcpServers": {
#   "voice-dictation": {
#     "command": "python3",
#     "args": ["/home/ubuntu/voice/mcp_voice_server.py", "--channel", "default"]
#   }
# }
```

### Local machine (Windows)

```powershell
# Install WinFsp + SSHFS-Win
# Mount remote voice folder as V:
net use V: \\sshfs.k\ubuntu@yourserver\voice

# Install Python dependencies
pip install sounddevice soundfile

# Run recorder
python voice_recorder.py --channel default
```

## Usage

1. Run `voice_recorder.py` on your local machine
2. Press ENTER → speak → press ENTER
3. In Claude Code on the server, type "dictate"
4. Claude reads and uses your spoken text

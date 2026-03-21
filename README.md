# Voice Dictation for Claude Code

Voice input for Claude Code running on remote servers over SSH/tmux.

Record audio on your local machine → auto-transcribed by Whisper on the server → Claude Code reads it via `/dictate` skill or MCP tool.

## Architecture

```
[Windows machine]                              [Remote server (castellatus)]
voice_recorder.py                              ~/voice/
  --channel production-main                      incoming/production-main/
  records audio ──→ V:\ (SSHFS mount) ──→          ↓ inotifywait
                                                    ↓ faster-whisper
                                                 transcripts/production-main/latest.txt
                                                    ↑
  "/dictate" in Claude Code ←── skill/MCP ──→   mcp_voice_server.py (auto-detects tmux)
```

## Components

| File | Where | Purpose |
|------|-------|---------|
| `voice_recorder.py` | Local (Windows/Mac/Linux) | Records audio via SSHFS mount, `--channel` targets a tmux session |
| `windows_recorder.py` | Local (Windows) | Records audio, uploads via SCP (no mount needed) |
| `mcp_voice_server.py` | Remote server | MCP server exposing `dictate` tool — auto-detects tmux session as channel |
| `transcribe_watcher.sh` | Remote server | Watches for new audio, transcribes with Whisper |
| `voice-watcher.service` | Remote server | systemd service for the watcher |
| `.claude/commands/dictate.md` | Platform repo | `/dictate` skill — reads voice input with MCP fallback to direct file read |

## Channels = tmux Sessions

Each Claude Code session auto-binds to its **tmux session name** as the voice channel. No manual config needed.

| tmux session | Recorder command | Transcript location |
|---|---|---|
| `production-main` | `--channel production-main` | `~/voice/transcripts/production-main/latest.txt` |
| `monitoring` | `--channel monitoring` | `~/voice/transcripts/monitoring/latest.txt` |
| `0` (default tmux) | `--channel 0` | `~/voice/transcripts/0/latest.txt` |
| _(no tmux)_ | _(no flag)_ | `~/voice/transcripts/default/latest.txt` |

**Server side** — both the MCP server and `/dictate` skill auto-detect the tmux session. No `--channel` arg needed in Claude Code settings.

**Recorder side** — you choose which session to target with `--channel`:

```powershell
# Target the production-main Claude Code session
C:\Python314\python.exe V:\voice_recorder.py --channel production-main

# Target the monitoring session
C:\Python314\python.exe V:\voice_recorder.py --channel monitoring
```

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
# Channel is auto-detected from tmux — no --channel arg needed
# "mcpServers": {
#   "voice-dictation": {
#     "command": "python3",
#     "args": ["/home/ubuntu/voice/mcp_voice_server.py"]
#   }
# }
```

### Local machine (Windows)

```powershell
# Install WinFsp + SSHFS-Win (https://winfsp.dev, https://github.com/winfsp/sshfs-win)
# Mount remote voice folder as V:
net use V: \\sshfs.k\ubuntu@castellatus.cloudgrow.tech\voice

# Install Python dependencies (use your Python with sounddevice)
C:\Python314\python.exe -m pip install sounddevice soundfile

# Run recorder targeting a specific Claude Code session
C:\Python314\python.exe V:\voice_recorder.py --channel production-main
```

**Alternative (no SSHFS mount)** — use `windows_recorder.py` which uploads via SCP:

```powershell
python windows_recorder.py --channel production-main
```

## Usage

1. Start the recorder on Windows with `--channel <tmux-session-name>`
2. Press ENTER → speak → press ENTER
3. In Claude Code on the server, type `/dictate`
4. Claude reads your spoken text and acts on it

The `/dictate` skill auto-detects the tmux session, reads the transcript, and treats the spoken text as your instruction.

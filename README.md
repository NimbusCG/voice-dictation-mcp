# Voice Dictation for Claude Code

Voice input for Claude Code running on remote servers over SSH/tmux.

Record audio on your local machine → transcribed by Whisper (locally or on server) → Claude Code reads it via `/dictate`.

## Architecture

```
[Windows machine]                              [Remote server (castellatus)]

Option A: Local transcription (--local, faster)
voice_recorder.py --local                      ~/voice/
  records audio                                  transcripts/{channel}/latest.txt ← written directly
  transcribes with Whisper ──→ V:\ mount ──→       ↑
                                                   reads
  "/dictate" in Claude Code ←─────────────────  /dictate skill

Option B: Remote transcription (default)
voice_recorder.py                              ~/voice/
  records audio ──→ V:\ mount ──→                incoming/{channel}/*.wav
                                                    ↓ inotifywait + faster-whisper
                                                 transcripts/{channel}/latest.txt
                                                    ↑
  "/dictate" in Claude Code ←── skill/MCP ──→   mcp_voice_server.py
```

## Quick Start (Windows)

```powershell
# 1. Mount remote voice folder as V:
net use V: \\sshfs.k\ubuntu@castellatus.cloudgrow.tech\voice

# 2. Install dependencies
C:\Python314\python.exe -m pip install sounddevice soundfile faster-whisper

# 3. Run with local transcription targeting a Claude Code session
C:\Python314\python.exe V:\voice_recorder.py --channel monitoring --local

# 4. In Claude Code on the server, type: /dictate
```

## Transcription Modes

### Local transcription (`--local`) — recommended

Whisper runs on your Windows machine. Transcribed text is written directly to the SSHFS mount. Faster because no .wav upload or server-side processing needed.

```powershell
C:\Python314\python.exe V:\voice_recorder.py --channel monitoring --local
C:\Python314\python.exe V:\voice_recorder.py --channel monitoring --local --model small  # more accurate
C:\Python314\python.exe V:\voice_recorder.py --channel monitoring --local --model tiny   # fastest
```

Requires: `pip install faster-whisper` (downloads ~150MB model on first run)

### Remote transcription (default)

Uploads .wav to the server. The `transcribe_watcher.sh` service picks it up and transcribes with Whisper server-side.

```powershell
C:\Python314\python.exe V:\voice_recorder.py --channel monitoring
```

No extra Python dependencies needed beyond `sounddevice soundfile`.

### SCP mode (no SSHFS mount)

If you can't mount V:, use `windows_recorder.py` which uploads via SCP:

```powershell
python windows_recorder.py --channel monitoring
```

## Components

| File | Where | Purpose |
|------|-------|---------|
| `voice_recorder.py` | Local (Windows/Mac/Linux) | Records audio, `--local` for local Whisper, `--channel` targets tmux session |
| `windows_recorder.py` | Local (Windows) | Records audio, uploads via SCP (no mount needed) |
| `mcp_voice_server.py` | Remote server | MCP server exposing `dictate` tool — auto-detects tmux session |
| `transcribe_watcher.sh` | Remote server | Watches for new .wav files, transcribes with Whisper |
| `voice-watcher.service` | Remote server | systemd service for the watcher |

## Channels = tmux Sessions

Each Claude Code session auto-binds to its **tmux session name** as the voice channel.

| tmux session | Recorder `--channel` | Transcript location |
|---|---|---|
| `production-main` | `--channel production-main` | `~/voice/transcripts/production-main/latest.txt` |
| `monitoring` | `--channel monitoring` | `~/voice/transcripts/monitoring/latest.txt` |
| `0` (default tmux) | `--channel 0` | `~/voice/transcripts/0/latest.txt` |
| _(no tmux)_ | _(no flag)_ | `~/voice/transcripts/default/latest.txt` |

**Server side** — the MCP server and `/dictate` skill auto-detect the tmux session name.

**Recorder side** — you choose which session to target with `--channel`.

## Setup

### Remote server

```bash
# Install dependencies
python3 -m venv ~/voice/venv
source ~/voice/venv/bin/activate
pip install faster-whisper
sudo apt install ffmpeg inotify-tools

# Install and start watcher service (for remote transcription mode)
sudo cp voice-watcher.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now voice-watcher

# MCP server config (~/.claude/settings.json) — channel auto-detected from tmux
# "mcpServers": {
#   "voice-dictation": {
#     "command": "python3",
#     "args": ["/home/ubuntu/voice/mcp_voice_server.py"]
#   }
# }
```

### Local machine (Windows)

```powershell
# Install WinFsp + SSHFS-Win
#   https://winfsp.dev
#   https://github.com/winfsp/sshfs-win

# Mount remote voice folder as V:
net use V: \\sshfs.k\ubuntu@castellatus.cloudgrow.tech\voice

# Install Python dependencies
C:\Python314\python.exe -m pip install sounddevice soundfile

# For local transcription mode (recommended):
C:\Python314\python.exe -m pip install faster-whisper
```

## Usage

1. Start the recorder on Windows: `C:\Python314\python.exe V:\voice_recorder.py --channel monitoring --local`
2. Press ENTER → speak → press ENTER
3. In Claude Code on the server, type `/dictate`
4. Claude reads your spoken text and acts on it

The `/dictate` skill auto-detects the tmux session, reads the transcript, and treats the spoken text as your instruction. Each `/dictate` call consumes the transcript so stale text isn't re-read.

## Whisper Models

For `--local` mode, choose a model with `--model`:

| Model | Size | Speed | Accuracy |
|-------|------|-------|----------|
| `tiny` | ~75MB | Fastest | Good for short commands |
| `base` | ~150MB | Fast | Default, good balance |
| `small` | ~500MB | Medium | Better accuracy |
| `medium` | ~1.5GB | Slow | Best accuracy |

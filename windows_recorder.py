#!/usr/bin/env python3
"""
Voice Recorder for Windows — Records audio and uploads to remote server.

Setup (run once in PowerShell):
    pip install sounddevice soundfile

Usage:
    python recorder.py

    Press ENTER to start recording, ENTER again to stop.
    Audio is automatically uploaded to the remote server via scp.

Configuration:
    Edit REMOTE_HOST and REMOTE_PATH below, or set environment variables:
        VOICE_REMOTE_HOST=ubuntu@castellatus.cloudgrow.tech
        VOICE_REMOTE_PATH=~/voice/incoming/
"""

import argparse
import os
import sys
import subprocess
import tempfile
import threading
from datetime import datetime

try:
    import sounddevice as sd
    import soundfile as sf
except ImportError:
    print("Missing dependencies. Run:")
    print("  pip install sounddevice soundfile")
    sys.exit(1)

# Configuration — edit these or set env vars
REMOTE_HOST = os.environ.get("VOICE_REMOTE_HOST", "ubuntu@castellatus.cloudgrow.tech")
REMOTE_BASE = os.environ.get("VOICE_REMOTE_PATH", "~/voice/incoming")
SAMPLE_RATE = 16000  # 16kHz is ideal for Whisper
CHANNELS_AUDIO = 1

# Channel set via --channel arg (tmux session name)
CHANNEL = "default"

# State
recording = False
audio_frames = []


def record_audio():
    """Record audio until stopped."""
    global recording, audio_frames
    audio_frames = []

    def callback(indata, frames, time, status):
        if recording:
            audio_frames.append(indata.copy())

    with sd.InputStream(samplerate=SAMPLE_RATE, channels=CHANNELS_AUDIO,
                        dtype='float32', callback=callback):
        while recording:
            sd.sleep(100)


def upload_file(filepath, filename):
    """Upload audio file to remote server via scp."""
    remote_dest = f"{REMOTE_HOST}:{REMOTE_BASE}/{CHANNEL}/{filename}"
    try:
        result = subprocess.run(
            ["scp", "-q", filepath, remote_dest],
            capture_output=True, text=True, timeout=30
        )
        if result.returncode == 0:
            print(f"  Uploaded to {remote_dest}")
            return True
        else:
            print(f"  Upload failed: {result.stderr.strip()}")
            return False
    except subprocess.TimeoutExpired:
        print("  Upload timed out")
        return False
    except FileNotFoundError:
        print("  scp not found. Make sure OpenSSH is installed.")
        print("  Windows 10+: Settings > Apps > Optional Features > OpenSSH Client")
        return False


def ensure_remote_channel_dir():
    """Create the channel subfolder on the remote server if it doesn't exist."""
    remote_dir = f"{REMOTE_BASE}/{CHANNEL}"
    try:
        subprocess.run(
            ["ssh", REMOTE_HOST, f"mkdir -p {remote_dir}"],
            capture_output=True, timeout=10
        )
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass  # Best effort — scp will fail with a clear error if dir missing


def main():
    global recording, CHANNEL

    parser = argparse.ArgumentParser(description="Record voice clips for Claude Code")
    parser.add_argument("--channel", default="default",
                        help="Target channel (tmux session name). e.g. --channel production-main")
    args = parser.parse_args()
    CHANNEL = args.channel

    ensure_remote_channel_dir()

    print("=" * 50)
    print("  Voice Recorder for Claude Code")
    print("=" * 50)
    print(f"  Remote:  {REMOTE_HOST}:{REMOTE_BASE}/{CHANNEL}/")
    print(f"  Channel: {CHANNEL}")
    print(f"  Sample rate: {SAMPLE_RATE}Hz")
    print()
    print("  Press ENTER to start recording")
    print("  Press ENTER again to stop and upload")
    print("  Type 'q' + ENTER to quit")
    print("=" * 50)

    while True:
        cmd = input("\n  Ready. Press ENTER to record (q to quit): ").strip().lower()
        if cmd == 'q':
            print("  Goodbye!")
            break

        # Start recording
        recording = True
        record_thread = threading.Thread(target=record_audio, daemon=True)
        record_thread.start()
        print("  ** RECORDING ** Press ENTER to stop...")

        input()  # Wait for ENTER to stop

        # Stop recording
        recording = False
        record_thread.join(timeout=2)

        if not audio_frames:
            print("  No audio captured.")
            continue

        # Save to temp WAV file
        import numpy as np
        audio_data = np.concatenate(audio_frames, axis=0)
        duration = len(audio_data) / SAMPLE_RATE
        print(f"  Recorded {duration:.1f}s of audio")

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"voice_{timestamp}.wav"

        # Save locally first
        local_dir = os.path.join(tempfile.gettempdir(), "voice_recordings")
        os.makedirs(local_dir, exist_ok=True)
        local_path = os.path.join(local_dir, filename)
        sf.write(local_path, audio_data, SAMPLE_RATE)
        print(f"  Saved locally: {local_path}")

        # Upload
        print("  Uploading...")
        upload_file(local_path, filename)
        print("  Done! Say 'dictate' in Claude Code to get the transcription.")


if __name__ == "__main__":
    main()

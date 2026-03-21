#!/usr/bin/env python3
"""Voice recorder that saves audio directly to a mounted remote folder for transcription."""

import argparse
import os
import platform
import shutil
import sys
import tempfile
import threading
import time
from datetime import datetime
from pathlib import Path

import sounddevice as sd
import soundfile as sf

# Mount point base for the remote server's ~/voice/incoming/ directory.
# V: maps to ~/voice/ on the server. Override with VOICE_MOUNT_PATH env var.
if "VOICE_MOUNT_PATH" in os.environ:
    MOUNT_BASE = Path(os.environ["VOICE_MOUNT_PATH"])
elif platform.system() == "Windows":
    MOUNT_BASE = Path("V:/incoming")
else:
    MOUNT_BASE = Path.home() / "voice_incoming" / "incoming"

# Channel is set via --channel arg in main(). Determines subfolder.
MOUNT_PATH = MOUNT_BASE  # Updated in main() after parsing args

SAMPLE_RATE = 16000
CHANNELS = 1
DTYPE = "float32"


def get_local_backup_dir() -> Path:
    """Get the local backup directory for recordings."""
    if platform.system() == "Windows":
        base = Path(os.environ.get("TEMP", tempfile.gettempdir()))
    else:
        base = Path(tempfile.gettempdir())
    backup_dir = base / "voice_recordings"
    backup_dir.mkdir(parents=True, exist_ok=True)
    return backup_dir


def check_mount() -> bool:
    """Check that the remote mount is accessible."""
    return MOUNT_PATH.exists() and MOUNT_PATH.is_dir()


def record_clip() -> tuple[str | None, float]:
    """Record audio until ENTER is pressed. Returns (filepath, duration_seconds)."""
    frames = []

    def callback(indata, frame_count, time_info, status):
        if status:
            print(f"  (audio status: {status})", file=sys.stderr)
        frames.append(indata.copy())

    stream = sd.InputStream(
        samplerate=SAMPLE_RATE,
        channels=CHANNELS,
        dtype=DTYPE,
        callback=callback,
    )

    stream.start()
    start_time = time.monotonic()
    stop_event = threading.Event()

    def show_timer():
        phases = ["||", "|", " ", "|"]
        i = 0
        while not stop_event.is_set():
            elapsed = time.monotonic() - start_time
            bar = phases[i % len(phases)]
            print(f"\r  {bar} RECORDING  {elapsed:5.1f}s {bar}  (press ENTER to stop)", end="", flush=True)
            i += 1
            stop_event.wait(0.25)
        print()

    timer = threading.Thread(target=show_timer, daemon=True)
    timer.start()

    input()
    stop_event.set()
    timer.join()

    stream.stop()
    stream.close()

    if not frames:
        return None, 0.0

    import numpy as np
    audio = np.concatenate(frames, axis=0)
    duration = len(audio) / SAMPLE_RATE

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"voice_{timestamp}.wav"

    # Save local backup
    backup_dir = get_local_backup_dir()
    backup_path = backup_dir / filename
    sf.write(str(backup_path), audio, SAMPLE_RATE)
    print(f"  Backup: {backup_path}")
    print(f"  Duration: {duration:.1f}s")

    # Copy to mounted remote folder
    remote_path = MOUNT_PATH / filename
    try:
        shutil.copy2(str(backup_path), str(remote_path))
        print(f"  Sent:   {remote_path}")
    except OSError as e:
        print(f"  ERROR: failed to write to mount ({e})")
        print(f"  Local backup is safe at {backup_path}")

    return str(backup_path), duration


def test_mic():
    """Record 2 seconds of audio and play it back to verify the mic."""
    print("Testing microphone: recording 2 seconds...")
    audio = sd.rec(int(2 * SAMPLE_RATE), samplerate=SAMPLE_RATE, channels=CHANNELS, dtype=DTYPE)
    sd.wait()
    print("Playing back...")
    sd.play(audio, samplerate=SAMPLE_RATE)
    sd.wait()
    print("Mic test complete. If you heard your voice, the mic works.")


def main():
    global MOUNT_PATH

    parser = argparse.ArgumentParser(description="Record voice clips for transcription")
    parser.add_argument("--test", action="store_true", help="Record 2s and play back to test mic")
    parser.add_argument("--channel", default="default",
                        help="Target channel (tmux session name). e.g. --channel production-main")
    args = parser.parse_args()

    if args.test:
        test_mic()
        return

    # Set mount path to channel subfolder
    MOUNT_PATH = MOUNT_BASE / args.channel
    MOUNT_PATH.mkdir(parents=True, exist_ok=True)

    if not check_mount():
        print(f"ERROR: Remote folder not mounted at {MOUNT_BASE}")
        print()
        if platform.system() == "Windows":
            print("  Mount it with:")
            print("    net use V: \\\\sshfs.k\\ubuntu@castellatus.cloudgrow.tech\\voice")
            print()
            print("  Requires WinFsp + SSHFS-Win installed:")
            print("    https://winfsp.dev")
            print("    https://github.com/winfsp/sshfs-win")
        else:
            print("  Mount it with:")
            print(f"    sshfs -o IdentityFile=~/.ssh/cloudgrow-key.pem,reconnect,ServerAliveInterval=15,ServerAliveCountMax=3 \\")
            print(f"      ubuntu@castellatus.cloudgrow.tech:/home/ubuntu/voice/incoming {MOUNT_BASE}")
        print()
        print("  Or set VOICE_MOUNT_PATH to point to your mount.")
        sys.exit(1)

    print("=" * 50)
    print("  Voice Recorder")
    print(f"  Channel: {args.channel}")
    print(f"  Mount:   {MOUNT_PATH}")
    print(f"  Backup:  {get_local_backup_dir()}")
    print("=" * 50)
    print("\nPress ENTER to start recording, ENTER again to stop.")
    print("Press Ctrl+C to quit.\n")

    try:
        while True:
            input("Ready — press ENTER to record...")
            filepath, duration = record_clip()

            if not filepath or duration <= 0.1:
                print("  (too short, skipped)")

            print()
    except KeyboardInterrupt:
        print("\nDone.")


if __name__ == "__main__":
    main()

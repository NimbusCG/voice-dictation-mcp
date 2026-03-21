#!/usr/bin/env python3
"""
Voice recorder with local or remote transcription.

Modes:
  --local    Transcribe on this machine with faster-whisper, write text to mount
  (default)  Upload .wav to mount, let server-side watcher transcribe

Both modes support --channel to target a specific Claude Code tmux session.

Usage:
  python voice_recorder.py --channel monitoring              # remote transcription
  python voice_recorder.py --channel monitoring --local      # local transcription (faster)
  python voice_recorder.py --test                            # mic test
"""

import argparse
import os
import platform
import shutil
import sys
import tempfile
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

import sounddevice as sd
import soundfile as sf

# Mount point base: V: maps to ~/voice/ on the server.
# Override with VOICE_MOUNT_PATH env var.
if "VOICE_MOUNT_PATH" in os.environ:
    VOICE_ROOT = Path(os.environ["VOICE_MOUNT_PATH"])
elif platform.system() == "Windows":
    VOICE_ROOT = Path("V:/")
else:
    VOICE_ROOT = Path.home() / "voice"

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
    return VOICE_ROOT.exists() and VOICE_ROOT.is_dir()


def load_whisper_model(model_name="base"):
    """Load faster-whisper model. Returns model or None if not available."""
    try:
        from faster_whisper import WhisperModel
        print(f"  Loading Whisper model '{model_name}'...", end="", flush=True)
        model = WhisperModel(model_name, device="cpu", compute_type="int8")
        print(" ready.")
        return model
    except ImportError:
        print("  ERROR: faster-whisper not installed.")
        print("  Install with: pip install faster-whisper")
        return None


def transcribe_local(model, audio_path: str) -> str:
    """Transcribe audio file using local Whisper model."""
    segments, info = model.transcribe(audio_path, beam_size=5)
    text = " ".join(seg.text.strip() for seg in segments)
    return text


def write_transcript(channel: str, text: str, audio_filename: str):
    """Write transcript to the remote mount's transcript folder."""
    transcript_dir = VOICE_ROOT / "transcripts" / channel
    transcript_dir.mkdir(parents=True, exist_ok=True)

    # Write latest.txt
    latest_file = transcript_dir / "latest.txt"
    latest_file.write_text(text + "\n")

    # Append to channel history
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    history_line = f"{timestamp}|{channel}|{audio_filename}|{text}\n"

    history_file = transcript_dir / "history.log"
    with open(history_file, "a") as f:
        f.write(history_line)

    # Append to global history
    global_history = VOICE_ROOT / "transcripts" / "history.log"
    global_history.parent.mkdir(parents=True, exist_ok=True)
    with open(global_history, "a") as f:
        f.write(history_line)


def record_clip(local_mode: bool, channel: str, whisper_model=None) -> tuple:
    """Record audio until ENTER is pressed. Returns (filepath, duration, text)."""
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
        return None, 0.0, None

    import numpy as np
    audio = np.concatenate(frames, axis=0)
    duration = len(audio) / SAMPLE_RATE

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"voice_{timestamp}.wav"

    # Save local backup
    backup_dir = get_local_backup_dir()
    backup_path = backup_dir / filename
    sf.write(str(backup_path), audio, SAMPLE_RATE)
    print(f"  Backup:   {backup_path}")
    print(f"  Duration: {duration:.1f}s")

    if local_mode and whisper_model:
        # LOCAL: transcribe here, write text to mount
        print("  Transcribing locally...", end="", flush=True)
        t0 = time.monotonic()
        text = transcribe_local(whisper_model, str(backup_path))
        elapsed = time.monotonic() - t0
        print(f" done ({elapsed:.1f}s)")

        if text.strip():
            write_transcript(channel, text.strip(), filename)
            print(f"  Written:  V:\\transcripts\\{channel}\\latest.txt")
            print(f"  ──────────────────────────────────────────────")
            print(f"  {text.strip()}")
            print(f"  ──────────────────────────────────────────────")
        else:
            print("  (no speech detected)")

        return str(backup_path), duration, text.strip() if text.strip() else None
    else:
        # REMOTE: copy .wav to mount, let server watcher transcribe
        incoming_dir = VOICE_ROOT / "incoming" / channel
        incoming_dir.mkdir(parents=True, exist_ok=True)
        remote_path = incoming_dir / filename
        try:
            shutil.copy2(str(backup_path), str(remote_path))
            print(f"  Sent:     {remote_path}")
        except OSError as e:
            print(f"  ERROR: failed to write to mount ({e})")
            print(f"  Local backup is safe at {backup_path}")

        return str(backup_path), duration, None


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
    parser = argparse.ArgumentParser(
        description="Record voice clips for Claude Code",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s --channel monitoring              Remote transcription (server-side Whisper)
  %(prog)s --channel monitoring --local      Local transcription (faster, needs faster-whisper)
  %(prog)s --test                            Test your microphone
  %(prog)s --channel monitoring --local --model small   Use a larger Whisper model
""")
    parser.add_argument("--test", action="store_true",
                        help="Record 2s and play back to test mic")
    parser.add_argument("--channel", default="default",
                        help="Target channel (tmux session name). e.g. --channel production-main")
    parser.add_argument("--local", action="store_true",
                        help="Transcribe locally with faster-whisper instead of uploading .wav")
    parser.add_argument("--model", default="base",
                        help="Whisper model size for --local mode (tiny/base/small/medium). Default: base")
    args = parser.parse_args()

    if args.test:
        test_mic()
        return

    if not check_mount():
        print(f"ERROR: Remote folder not mounted at {VOICE_ROOT}")
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
            print(f"      ubuntu@castellatus.cloudgrow.tech:/home/ubuntu/voice {VOICE_ROOT}")
        print()
        print("  Or set VOICE_MOUNT_PATH to point to your mount.")
        sys.exit(1)

    # Load whisper model if local mode
    whisper_model = None
    if args.local:
        whisper_model = load_whisper_model(args.model)
        if not whisper_model:
            print("\nFalling back to remote transcription mode.\n")
            args.local = False

    mode_label = "LOCAL transcription" if args.local else "REMOTE transcription (server-side)"
    print("=" * 56)
    print("  Voice Recorder for Claude Code")
    print(f"  Channel: {args.channel}")
    print(f"  Mode:    {mode_label}")
    if args.local:
        print(f"  Model:   {args.model}")
    print(f"  Mount:   {VOICE_ROOT}")
    print(f"  Backup:  {get_local_backup_dir()}")
    print("=" * 56)
    print("\nPress ENTER to start recording, ENTER again to stop.")
    print("Press Ctrl+C to quit.\n")

    try:
        while True:
            input("Ready — press ENTER to record...")
            filepath, duration, text = record_clip(args.local, args.channel, whisper_model)

            if not filepath or duration <= 0.1:
                print("  (too short, skipped)")
            elif args.local and text:
                print("  >> Type /dictate in Claude Code to read this.")

            print()
    except KeyboardInterrupt:
        print("\nDone.")


if __name__ == "__main__":
    main()

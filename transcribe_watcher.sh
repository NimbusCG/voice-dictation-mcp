#!/bin/bash
# Voice Transcription Watcher (Channel-aware)
# Watches ~/voice/incoming/ and all subdirectories (channels) for new audio files.
# Transcribes with Whisper and writes to the matching channel transcript folder.
#
# Channel structure:
#   ~/voice/incoming/platform/   → ~/voice/transcripts/platform/latest.txt
#   ~/voice/incoming/crm/        → ~/voice/transcripts/crm/latest.txt
#   ~/voice/incoming/default/    → ~/voice/transcripts/default/latest.txt
#   ~/voice/incoming/*.wav       → ~/voice/transcripts/default/latest.txt (root = default)
#
# Usage: ./transcribe_watcher.sh [--model base|small|tiny]

VOICE_DIR="$HOME/voice"
INCOMING="$VOICE_DIR/incoming"
TRANSCRIPTS="$VOICE_DIR/transcripts"
PROCESSED="$VOICE_DIR/processed"
VENV="$VOICE_DIR/venv"
MODEL="${1:-base}"

# Ensure default channel exists
mkdir -p "$INCOMING/default" "$TRANSCRIPTS/default" "$PROCESSED/default"

echo "[voice-watcher] Watching $INCOMING (+ subfolders) for audio files (model: $MODEL)"
echo "[voice-watcher] Channels are subfolders of incoming/"

# Pre-download model on first run
source "$VENV/bin/activate"
python3 -c "from faster_whisper import WhisperModel; WhisperModel('$MODEL', device='cpu', compute_type='int8')" 2>/dev/null
echo "[voice-watcher] Model loaded. Ready."

# Watch recursively (-r) and include the relative path (%w%f)
inotifywait -r -m -e close_write --format '%w%f' "$INCOMING" | while read -r FILEPATH; do
    # Get just the filename
    FILE=$(basename "$FILEPATH")

    # Only process audio files
    case "$FILE" in
        *.wav|*.mp3|*.m4a|*.ogg|*.flac|*.webm)
            # Determine channel from subfolder
            RELPATH="${FILEPATH#$INCOMING/}"
            DIR=$(dirname "$RELPATH")
            if [ "$DIR" = "." ]; then
                CHANNEL="default"
            else
                # Use first path component as channel name
                CHANNEL=$(echo "$DIR" | cut -d'/' -f1)
            fi

            # Ensure channel transcript/processed dirs exist
            mkdir -p "$TRANSCRIPTS/$CHANNEL" "$PROCESSED/$CHANNEL"

            echo "[voice-watcher] [$CHANNEL] Transcribing: $FILE"

            # Transcribe
            RESULT=$(python3 -c "
from faster_whisper import WhisperModel
model = WhisperModel('$MODEL', device='cpu', compute_type='int8')
segments, info = model.transcribe('$FILEPATH', beam_size=5)
text = ' '.join(seg.text.strip() for seg in segments)
print(text)
" 2>/dev/null)

            if [ -n "$RESULT" ]; then
                # Write transcript to channel folder
                echo "$RESULT" > "$TRANSCRIPTS/$CHANNEL/latest.txt"
                echo "$(date -u +%Y-%m-%dT%H:%M:%SZ)|$CHANNEL|$FILE|$RESULT" >> "$TRANSCRIPTS/$CHANNEL/history.log"
                # Also write to global history
                echo "$(date -u +%Y-%m-%dT%H:%M:%SZ)|$CHANNEL|$FILE|$RESULT" >> "$TRANSCRIPTS/history.log"
                echo "[voice-watcher] [$CHANNEL] >> $RESULT"

                # Move processed file
                mv "$FILEPATH" "$PROCESSED/$CHANNEL/$FILE"
            else
                echo "[voice-watcher] [$CHANNEL] ERROR: Empty transcription for $FILE"
            fi
            ;;
        *)
            # Ignore non-audio files
            ;;
    esac
done

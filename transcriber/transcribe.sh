#!/usr/bin/env bash
# Транскрипція аудіо через faster-whisper
# Використання: ./transcribe.sh <audio_file> -o <output_dir> -m <model>

set -euo pipefail

INPUT="$1"
OUTPUT_DIR="."
MODEL="medium"

shift
while [[ $# -gt 0 ]]; do
    case "$1" in
        -o) OUTPUT_DIR="$2"; shift 2 ;;
        -m) MODEL="$2"; shift 2 ;;
        *) shift ;;
    esac
done

BASENAME="$(basename "${INPUT%.*}")"
mkdir -p "$OUTPUT_DIR"

# Use the project venv
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_PYTHON="${SCRIPT_DIR}/../venv/bin/python3"

if [ ! -f "$VENV_PYTHON" ]; then
    VENV_PYTHON="python3"
fi

"$VENV_PYTHON" -c "
from faster_whisper import WhisperModel

model = WhisperModel('${MODEL}', device='cpu', compute_type='int8')
segments, info = model.transcribe('${INPUT}', language='uk')

print(f'Language: {info.language} (probability {info.language_probability:.2f})')
print(f'Duration: {info.duration:.1f}s')

with open('${OUTPUT_DIR}/${BASENAME}.txt', 'w') as f:
    for segment in segments:
        line = f'[{segment.start:.1f}s - {segment.end:.1f}s] {segment.text}'
        print(line)
        f.write(segment.text.strip() + ' ')
"

echo "Done: ${OUTPUT_DIR}/${BASENAME}.txt"

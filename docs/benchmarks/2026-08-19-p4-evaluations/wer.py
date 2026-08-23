#!/usr/bin/env python3
"""Levenshtein word error rate: (S + D + I) / reference words.

Reproduce:
  say -o speech.aiff -f reference.txt --file-format=AIFF
  ffmpeg -i speech.aiff -vn -acodec pcm_s16le -ar 16000 -ac 1 p4b.wav
  ffmpeg -i speech.aiff -vn -acodec libmp3lame -ar 16000 -ac 1 -b:a 64k p4b.mp3
  whisper-cli -m ggml-small.en.bin -f p4b.wav -np -nt > transcript-wav.txt
  whisper-cli -m ggml-small.en.bin -f p4b.mp3 -np -nt > transcript-mp3.txt
  python3 wer.py
"""
import re
from pathlib import Path


def norm(text: str) -> list[str]:
    return re.sub(r"[^\w\s]", "", text.casefold()).split()


def wer(reference: list[str], hypothesis: list[str]) -> float:
    rows = len(reference) + 1
    cols = len(hypothesis) + 1
    dp = list(range(cols))
    for i in range(1, rows):
        prev_diag, dp[0] = dp[0], i
        for j in range(1, cols):
            prev_diag, dp[j] = dp[j], min(
                dp[j] + 1,          # deletion
                dp[j - 1] + 1,      # insertion
                prev_diag + (reference[i - 1] != hypothesis[j - 1]),  # sub
            )
    return dp[-1] / len(reference)


if __name__ == "__main__":
    here = Path(__file__).parent
    reference = norm((here / "reference.txt").read_text())
    for fmt in ("wav", "mp3"):
        hyp = norm((here / f"transcript-{fmt}.txt").read_text())
        print(f"{fmt}: words={len(hyp)} WER={wer(reference, hyp):.4f}")

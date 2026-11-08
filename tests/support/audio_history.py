"""Synthetic PCM data for archive contracts; no microphone or real audio."""

import io
import wave


def wav_bytes(frames=1600):
    output = io.BytesIO()
    with wave.open(output, "wb") as stream:
        stream.setnchannels(1)
        stream.setsampwidth(2)
        stream.setframerate(16000)
        stream.writeframes(b"\x10\x00" * frames)
    return output.getvalue()

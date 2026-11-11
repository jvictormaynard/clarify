"""Play the shared dictation cues on a recording lifecycle worker."""

import sys
import wave
from pathlib import Path


def play_dictation_cue(starting: bool) -> None:
    """Finish the start cue before capture; let Windows play stop asynchronously."""
    roots = []
    if root := getattr(sys, "_MEIPASS", None):
        roots.append(Path(root))
    if getattr(sys, "frozen", False):
        roots.append(Path(sys.executable).resolve().parent)
    roots.append(Path(__file__).resolve().parents[2])
    name = "dictation-start.wav" if starting else "dictation-stop.wav"
    path = next(
        root / "assets" / "sounds" / name
        for root in roots
        if (root / "assets" / "sounds" / name).is_file()
    )
    if sys.platform == "win32":
        import winsound

        flags = winsound.SND_FILENAME | winsound.SND_NODEFAULT
        if not starting:
            flags |= winsound.SND_ASYNC
        winsound.PlaySound(str(path), flags)
    else:
        import sounddevice

        with wave.open(str(path), "rb") as audio:
            with sounddevice.RawOutputStream(
                samplerate=audio.getframerate(),
                channels=audio.getnchannels(),
                dtype="int16",
            ) as stream:
                stream.write(audio.readframes(audio.getnframes()))

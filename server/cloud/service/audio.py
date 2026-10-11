import hashlib
import subprocess
import wave
from pathlib import Path

from .ledger import Rejected


def fingerprint(upload, language):
    digest = hashlib.sha256(language.encode() + b"\0")
    for chunk in upload.chunks():
        digest.update(chunk)
    upload.seek(0)
    return digest.hexdigest()


def decode(upload, directory):
    # Do not trust the extension, MIME type, metadata or a client duration.
    source, target = Path(directory) / "input", Path(directory) / "clip.wav"
    with source.open("wb") as stream:
        for chunk in upload.chunks():
            stream.write(chunk)
    try:
        subprocess.run(
            [
                "ffmpeg",
                "-nostdin",
                "-v",
                "error",
                "-threads",
                "1",
                "-protocol_whitelist",
                "file,pipe",
                "-format_whitelist",
                "wav,mp3,mov,flac,ogg,matroska,webm,aac",
                "-i",
                str(source),
                "-map",
                "0:a:0",
                "-vn",
                "-sn",
                "-dn",
                "-ac",
                "1",
                "-ar",
                "16000",
                "-t",
                "301",
                "-fs",
                "9632100",
                "-f",
                "wav",
                "-y",
                str(target),
            ],
            check=True,
            timeout=15,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        with wave.open(str(target)) as audio:
            duration_ms = (
                audio.getnframes() * 1000 + audio.getframerate() - 1
            ) // audio.getframerate()
        if not 250 <= duration_ms <= 300000:
            raise Rejected("invalid_duration", 400)
        return target, duration_ms
    except (subprocess.SubprocessError, OSError, wave.Error):
        raise Rejected("invalid_audio", 400) from None

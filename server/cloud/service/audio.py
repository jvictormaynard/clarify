import hashlib
import subprocess
import wave
from pathlib import Path

from .ledger import Rejected


def fingerprint(
    upload, language, *, cleanup_level=None, writing_style=None, output_language=None
):
    digest = hashlib.sha256(language.encode() + b"\0")
    if cleanup_level is not None:
        from shared.dictation_policy import cleanup_level as parse_cleanup_level

        level = parse_cleanup_level(cleanup_level)
        digest.update(b"cleanup_level\0" + level.value.encode() + b"\0")
    if writing_style is not None:
        from shared.writing_style_policy import writing_style as parse_writing_style

        style = parse_writing_style(writing_style)
        digest.update(b"writing_style\0" + style.value.encode() + b"\0")
    if output_language is not None:
        from shared.output_preferences import output_language as parse_output_language

        target = parse_output_language(output_language)
        if target is None:
            raise ValueError("invalid_output_language")
        digest.update(b"output_language\0" + target.encode() + b"\0")
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

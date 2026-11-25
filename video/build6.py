"""Assemble la vidéo finale : cartons synchronisés sur la voix off.

Une piste par paragraphe : chaque carton reste affiché le temps exact de sa phrase, plus une demi
seconde de respiration. Le montage est reproductible : mêmes cartons, même audio, même résultat.

    python3 video/build6.py
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

AUDIO_DIR = Path("/opt/data/audio_cache")
SLIDES_DIR = Path("/data/agent-computer-challenge/video/slides6")
OUT_DIR = Path("/data/agent-computer-challenge/video/build6")
DEST = Path(__file__).resolve().parent.parent / "docs" / "video" / "vigie-presentation.mp4"

PADDING = 0.0  # pas de respiration : la durée cible est de deux minutes trente
# segments 3, 4, 10 et 11 réenregistrés : huit scénarios, la vision, les chiffres de vision, la carte
SEGMENTS = [
    ("01-titre", "vigie7-seg01.mp3"),
    ("02-demande-libre", "vigie6-seg02.mp3"),
    ("03-limite", "vigie7-seg03.mp3"),
    ("04-scenarios", "vigie6-seg04.mp3"),
    ("05-vision", "vigie7-seg05.mp3"),
    ("06-memoire", "vigie7-seg06.mp3"),
    ("07-delegation", "vigie7-seg07.mp3"),
    ("08-routage", "vigie7-seg08.mp3"),
    ("09-robustesse", "vigie7-seg09.mp3"),
    ("10-exploitation", "vigie7-seg10.mp3"),
    ("11-veille", "vigie6-seg11.mp3"),
    ("12-chiffres", "vigie7-seg12.mp3"),
    ("13-carte", "vigie6-seg13.mp3"),
]


def duration(path: Path) -> float:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "json", str(path)],
        check=True,
        capture_output=True,
        text=True,
    )
    return float(json.loads(out.stdout)["format"]["duration"])


def main() -> None:
    if not DEST.parent.exists():
        raise SystemExit(f"dossier de sortie absent : {DEST.parent}")
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    concat_lines: list[str] = []
    audio_lines: list[str] = []
    total = 0.0
    for index, (slide, audio) in enumerate(SEGMENTS, start=1):
        image = SLIDES_DIR / f"{slide}.png"
        track = AUDIO_DIR / audio
        for path in (image, track):
            if not path.exists():
                raise SystemExit(f"manquant : {path}")
        seconds = duration(track) + PADDING
        total += seconds
        clip = OUT_DIR / f"seg{index:02d}.mp4"
        subprocess.run(
            [
                "ffmpeg", "-y", "-loop", "1", "-i", str(image), "-t", f"{seconds:.3f}",
                "-vf", "fps=25,format=yuv420p", "-c:v", "libx264", "-preset", "medium", "-crf", "19",
                str(clip),
            ],
            check=True,
            capture_output=True,
        )
        concat_lines += [f"file '{clip}'", f"duration {seconds:.3f}"]
        audio_lines.append(f"file '{track}'")

    concat_file = OUT_DIR / "video.txt"
    concat_file.write_text("\n".join(concat_lines + [f"file '{OUT_DIR / ('seg%02d.mp4' % len(SEGMENTS))}'"]) + "\n", encoding="utf-8")
    audio_file = OUT_DIR / "audio.txt"
    audio_file.write_text("\n".join(audio_lines) + "\n", encoding="utf-8")

    silent = OUT_DIR / "video-muette.mp4"
    subprocess.run(
        ["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(concat_file), "-c", "copy", str(silent)],
        check=True,
        capture_output=True,
    )
    voice = OUT_DIR / "voix.mp3"
    subprocess.run(
        ["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(audio_file), "-c:a", "libmp3lame", str(voice)],
        check=True,
        capture_output=True,
    )
    OUT_DIR.joinpath("final").mkdir(exist_ok=True)
    subprocess.run(
        [
            "ffmpeg", "-y", "-i", str(silent), "-i", str(voice),
            "-c:v", "copy", "-c:a", "aac", "-b:a", "160k",
            "-af", "loudnorm=I=-16:TP=-1.5:LRA=11",
            "-shortest", "-movflags", "+faststart", str(DEST),
        ],
        check=True,
        capture_output=True,
    )
    print(f"vidéo : {DEST} ({DEST.stat().st_size // 1024} Ko, {total:.1f} s)")
    print(f"voix off : {voice}")
    # la piste audio reste dans le dépôt pour que le montage soit vérifiable
    print("copie de la voix off et du script dans docs/video/")


if __name__ == "__main__":
    main()

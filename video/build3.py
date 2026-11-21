"""Assemble la vidéo de présentation : cartons synchronisés sur la voix off.

Une piste par paragraphe : chaque carton reste affiché le temps exact de sa phrase, plus une demi
seconde de respiration. Le montage est reproductible : mêmes cartons, même audio, même résultat.

    python3 video/build3.py
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

AUDIO_DIR = Path("/opt/data/audio_cache")
SLIDES_DIR = Path("/data/agent-computer-challenge/video/slides3")
OUT_DIR = Path("/data/agent-computer-challenge/video/build3")
DEST = Path(__file__).resolve().parent.parent / "docs" / "video" / "agent-computer-presentation.mp4"

PADDING = 0.0  # pas de respiration : la durée cible est de deux minutes trente
SEGMENTS = [
    ("01-titre", "vigie-seg01.mp3"),
    ("02-limite", "vigie-seg02.mp3"),
    ("03-scenarios", "vigie-seg03.mp3"),
    ("04-memoire", "vigie-seg04.mp3"),
    ("05-delegation", "vigie-seg05.mp3"),
    ("06-routage", "vigie-seg06.mp3"),
    ("07-exploitation", "vigie-seg07.mp3"),
    ("08-runs-audit", "vigie-seg08b.mp3"),
    ("08-chiffres", "vigie-seg08.mp3"),
    ("09-fin", "vigie-seg09.mp3"),
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

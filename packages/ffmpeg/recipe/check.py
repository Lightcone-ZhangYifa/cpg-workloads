#!/usr/bin/env python3
"""Exercise the installed FFmpeg executables and static libavutil in a fresh work tree."""
from __future__ import annotations

import argparse
import array
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import wave


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--prefix", type=Path, required=True)
    parser.add_argument("--build", type=Path, required=True)
    args = parser.parse_args()
    prefix = args.prefix.resolve()
    args.build.mkdir(parents=True, exist_ok=True)
    work = Path(tempfile.mkdtemp(prefix="ffmpeg-functional-", dir=args.build))
    report = {"resource": "ffmpeg", "status": "running", "prefix": str(prefix), "commands": [],
              "functional_assertions": [], "negative_checks": []}
    environment = dict(os.environ)
    for name in ("LD_PRELOAD", "LD_LIBRARY_PATH", "CPATH", "LIBRARY_PATH", "C_INCLUDE_PATH", "PKG_CONFIG_PATH"):
        environment.pop(name, None)
    environment.update(PATH="/usr/bin:/bin", LC_ALL="C")

    def run(label, argv, *, negative=None):
        argv = [str(x) for x in argv]
        value = subprocess.run(argv, cwd=work, capture_output=True, env=environment, timeout=90)
        (work / (label + ".stdout")).write_bytes(value.stdout)
        (work / (label + ".stderr")).write_bytes(value.stderr)
        report["commands"].append({"label": label, "argv": argv, "returncode": value.returncode,
                                   "stdout": label + ".stdout", "stderr": label + ".stderr"})
        if negative:
            text = (value.stdout + value.stderr).decode(errors="replace")
            if value.returncode == 0 or negative.lower() not in text.lower():
                raise AssertionError("Invalid input was not rejected as expected: " + label)
            report["negative_checks"].append({"label": label, "returncode": value.returncode, "diagnostic": negative})
        elif value.returncode:
            raise RuntimeError("Installed consumer failed: " + label + ": " + value.stderr.decode(errors="replace"))
        return value.stdout

    try:
        ffmpeg, ffprobe = prefix / "bin/ffmpeg", prefix / "bin/ffprobe"
        version = run("version", [ffmpeg, "-version"]).decode()
        if not version.startswith("ffmpeg version "):
            raise AssertionError("Unexpected FFmpeg version output")
        profile = json.loads((prefix / "share/compiler-playground/ffmpeg/profile.json").read_text())
        if profile["upstream_tests"]["status"] != "passed" or profile["upstream_tests"]["executed"] < 1:
            raise AssertionError("The exact packaged build did not execute upstream FATE tests")
        pixels = bytes((frame * 37 + y * 17 + x * 13) % 256 for frame in range(5) for y in range(16) for x in range(16))
        (work / "original.gray").write_bytes(pixels)
        run("video-encode", [ffmpeg, "-v", "error", "-nostdin", "-f", "rawvideo", "-pixel_format", "gray", "-video_size", "16x16", "-framerate", "5", "-i", "original.gray", "-c:v", "ffv1", "-level", "3", "video.mkv"])
        video = json.loads(run("video-probe", [ffprobe, "-v", "error", "-show_streams", "-show_format", "-of", "json", "video.mkv"]))
        stream = video["streams"][0]
        if (stream["codec_name"], stream["width"], stream["height"], stream["pix_fmt"]) != ("ffv1", 16, 16, "gray"):
            raise AssertionError("Encoded video stream identity/shape is wrong")
        run("video-decode", [ffmpeg, "-v", "error", "-nostdin", "-i", "video.mkv", "-pix_fmt", "gray", "-f", "rawvideo", "decoded.gray"])
        if (work / "decoded.gray").read_bytes() != pixels:
            raise AssertionError("Lossless FFV1 roundtrip changed pixels")
        report["functional_assertions"].append({"name": "lossless-video-roundtrip", "frames": 5, "bytes": len(pixels), "sha256": hashlib.sha256(pixels).hexdigest(), "stream": stream})
        samples = array.array("h", (((i * 1103) % 60001) - 30000 for i in range(512))).tobytes()
        with wave.open(str(work / "original.wav"), "wb") as file:
            file.setparams((1, 2, 8000, 512, "NONE", "not compressed"))
            file.writeframes(samples)
        run("audio-float", [ffmpeg, "-v", "error", "-nostdin", "-i", "original.wav", "-c:a", "pcm_f32le", "float.wav"])
        audio = json.loads(run("audio-probe", [ffprobe, "-v", "error", "-show_streams", "-of", "json", "float.wav"]))["streams"][0]
        if (audio["codec_name"], int(audio["sample_rate"]), audio["channels"]) != ("pcm_f32le", 8000, 1):
            raise AssertionError("Audio conversion metadata is wrong")
        run("audio-int16", [ffmpeg, "-v", "error", "-nostdin", "-i", "float.wav", "-c:a", "pcm_s16le", "roundtrip.wav"])
        with wave.open(str(work / "roundtrip.wav"), "rb") as file:
            if file.getnframes() != 512 or file.readframes(512) != samples:
                raise AssertionError("PCM integer/float/integer roundtrip changed samples")
        report["functional_assertions"].append({"name": "pcm-audio-roundtrip", "samples": 512, "sample_bytes_sha256": hashlib.sha256(samples).hexdigest(), "stream": audio})
        (work / "bad-media").write_bytes(b"This is deliberately not a supported media file.\x00\x01")
        run("reject-malformed-media", [ffprobe, "-v", "error", "-show_streams", "bad-media"], negative="Invalid data")
        run("reject-unknown-codec", [ffmpeg, "-v", "error", "-nostdin", "-i", "original.wav", "-c:a", "cpg_invalid_codec", "bad.wav"], negative="Unknown encoder")
        run("reject-invalid-option", [ffmpeg, "-cpg-invalid-option"], negative="Unrecognized option")
        consumer = Path(__file__).parent / "consumer.c"
        run("api-compile", ["/usr/bin/cc", "-std=c11", "-Wall", "-Wextra", "-Werror", "-I" + str(prefix / "include"), consumer, prefix / "lib/libavutil.a", "-lm", "-pthread", "-o", work / "consumer"])
        api = json.loads(run("api-run", [work / "consumer"]))
        if api != {"sha256_abc": "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad", "invalid_color_rejected": True, "version_match": True}:
            raise AssertionError("Static libavutil consumer returned an unexpected result")
        report["functional_assertions"].append({"name": "installed-static-libavutil-api", **api})
        report.update(status="passed", positive_workflows=3, negative_cli_checks=3, negative_api_checks=1,
                      upstream_tests_for_packaged_build=profile["upstream_tests"]["executed"])
    except Exception as error:
        report.update(status="failed", error=f"{type(error).__name__}: {error}")
        raise
    finally:
        (work / "summary.json").write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
        print(json.dumps(report, sort_keys=True))


if __name__ == "__main__":
    main()

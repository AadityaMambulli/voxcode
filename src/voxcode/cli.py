"""Command-line interface for voxcode."""

from __future__ import annotations

import argparse
import sys
from dataclasses import replace

from .audio import list_devices
from .config import Config, load_config, save_config
from .core import doctor, listen, speak
from .ptt import run_ptt
from .stt import SttEngine, download_model


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="voxcode")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("devices", help="list audio devices")
    speak_parser = sub.add_parser("speak", help="speak text")
    speak_parser.add_argument("text")
    listen_parser = sub.add_parser("listen", help="record and transcribe speech")
    listen_parser.add_argument("--seconds", type=float)
    listen_parser.add_argument("--verbose", action="store_true")
    listen_parser.add_argument("--debug-vad", action="store_true")
    sub.add_parser("test", help="speak and transcribe a four-second recording")
    ptt_parser = sub.add_parser("ptt", help="run push-to-talk dictation")
    ptt_parser.add_argument(
        "--yes",
        action="store_true",
        help="download the missing speech model without prompting",
    )
    download_parser = sub.add_parser(
        "download-model", help="download and verify a local speech model"
    )
    download_parser.add_argument("--model", default="small")
    sub.add_parser("doctor", help="check the real local voice setup")
    sub.add_parser("setup", help="choose and save audio devices")
    config_parser = sub.add_parser("config", help="show configuration")
    config_parser.add_argument("--path", action="store_true")
    voice_parser = sub.add_parser("voice", help="enable or disable voice mode")
    voice_parser.add_argument("state", choices=["on", "off"])
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        config = load_config()
        if args.command == "devices":
            return _devices()
        if args.command == "speak":
            result = speak(args.text)
            print(f"[OK] TTS engine: {result.engine}")
            return 0
        if args.command == "listen":
            if args.seconds is not None:
                config = replace(config, fixed_seconds=args.seconds)
            if config.legacy_ignored:
                print(
                    "[WARN] Legacy config detected: saved device and default settings "
                    "were ignored; run `voxcode setup` to choose settings."
                )
            result = listen(
                config,
                language=config.language,
                verbose=args.verbose,
                debug_vad=args.debug_vad,
            )
            print(f"language: {config.language or 'auto-detect'}")
            print(f"transcript: {_console_text(result.transcript)}")
            print(f"recording_seconds: {result.record_seconds:.2f}")
            print(f"transcription_seconds: {result.transcription_seconds:.2f}")
            return 0
        if args.command == "test":
            result = speak("voxcode audio test")
            print(f"[OK] TTS engine: {result.engine}")
            listened = listen(config)
            print(f"transcript: {listened.transcript}")
            print(f"recording_seconds: {listened.record_seconds:.2f}")
            print(f"transcription_seconds: {listened.transcription_seconds:.2f}")
            return 0
        if args.command == "ptt":
            return run_ptt(config, download_yes=args.yes)
        if args.command == "download-model":
            path = download_model(
                args.model,
                progress=lambda message: print(message, flush=True),
            )
            engine = SttEngine(
                args.model,
                config.compute_type,
                progress=lambda message: print(message, flush=True),
                local_only=True,
            )
            load_seconds = engine.preload(local_only=True)
            print(
                f"[OK] speech model {args.model!r} verified from {path} "
                f"in {load_seconds:.2f}s"
            )
            return 0
        if args.command == "doctor":
            return _doctor(config)
        if args.command == "setup":
            return _setup(config)
        if args.command == "config":
            if args.path:
                from .config import config_path
                print(config_path())
            else:
                _print_config(config)
            return 0
        if args.command == "voice":
            saved = replace(config, voice_enabled=args.state == "on")
            path = save_config(saved, fields={"voice_enabled"})
            print(f"voice {args.state}; saved {path}")
            return 0
    except (RuntimeError, ValueError) as exc:
        print(f"[FAIL] {exc}", file=sys.stderr)
        return 1
    return 1


def _devices() -> int:
    devices = list_devices()
    if not devices:
        print("[FAIL] no audio devices found")
        return 1
    for device in devices:
        directions = []
        if device.max_input_channels:
            directions.append("input")
        if device.max_output_channels:
            directions.append("output")
        defaults = []
        if device.is_default_input:
            defaults.append("default-input")
        if device.is_default_output:
            defaults.append("default-output")
        suffix = ", ".join(defaults)
        if suffix:
            suffix = f" [{suffix}]"
        print(
            f"{device.index}: {device.name} | {device.hostapi} | "
            f"{'/'.join(directions) or 'none'}{suffix}"
        )
    return 0


def _doctor(config: Config) -> int:
    failed = False
    for name, ok, detail in doctor(config):
        marker = "OK" if ok else "FAIL"
        print(f"[{marker}] {name}: {detail}")
        if not ok:
            failed = True
            print(f"       Install/configure hint: {_hint(name)}")
    return 1 if failed else 0


def _hint(name: str) -> str:
    if "sounddevice" in name or "audio" in name:
        return "pip install -e .[audio]"
    if "faster-whisper" in name:
        return "pip install -e .[stt]"
    if "TTS" in name:
        return "Install Piper, or use the platform fallback documented by voxcode."
    if "VAD" in name:
        return "Install with `pip install -e .[vad]`."
    if "PTT" in name:
        return "PTT requires Windows 10/11 and a free function key such as F9."
    if "Python" in name:
        return "Use a Python interpreter in the supported range >=3.10,<3.14."
    return "Review the reported reason."


def _console_text(text: str) -> str:
    encoding = sys.stdout.encoding or "utf-8"
    return text.encode(encoding, errors="replace").decode(encoding, errors="replace")


def _setup(config: Config) -> int:
    devices = list_devices()
    input_devices = [d for d in devices if d.max_input_channels]
    output_devices = [d for d in devices if d.max_output_channels]
    input_device = _choose_device("input", input_devices)
    output_device = _choose_device("output", output_devices)
    language = input("Language (blank for auto-detect): ").strip() or None
    saved = replace(
        config,
        input_device=None,
        output_device=None,
        input_device_name=input_device.name,
        input_device_hostapi=input_device.hostapi,
        output_device_name=output_device.name,
        output_device_hostapi=output_device.hostapi,
        language=language,
    )
    path = save_config(
        saved,
        fields={
            "input_device_name", "input_device_hostapi",
            "output_device_name", "output_device_hostapi", "language",
        },
    )
    print(f"saved input={input_device.name}, output={output_device.name} to {path}")
    return 0


def _choose_device(direction: str, devices: list) -> object:
    if not devices:
        raise RuntimeError(f"No {direction} devices found")
    print(f"Available {direction} devices:")
    for device in devices:
        print(f"  {device.index}: {device.name} ({device.hostapi})")
    while True:
        try:
            choice = input(f"Choose {direction} device index: ").strip()
            selected = next(device for device in devices if device.index == int(choice))
        except (ValueError, StopIteration):
            print("Enter one of the listed numeric indexes.")
            continue
        return selected


def _print_config(config: Config) -> None:
    from .config import config_path
    print(f"path = {config_path()}")
    for key, value in config.__dict__.items():
        if key in {"sources", "legacy_ignored"}:
            continue
        print(f"{key} = {value!r} ({config.sources.get(key, 'default')})")
    if config.legacy_ignored:
        print("legacy config: device and saved default settings ignored; run `voxcode setup`")


if __name__ == "__main__":
    raise SystemExit(main())

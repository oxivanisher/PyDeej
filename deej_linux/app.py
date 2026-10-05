"""
Minimal deej client for Linux (PipeWire via pipewire-pulse, or plain PulseAudio).

Reads the standard deej serial format ("512|1023|0|...|780\\n", values 0..1023)
and sets volumes for master, mic, specific apps, or everything unmapped.
"""
import argparse
import logging
import os
import sys
import time

import pulsectl
import serial

from . import config as cfgmod

log = logging.getLogger("deej")

EVENT_ROLE = "sink-input-by-media-role:event"  # stored volume for new system/notification sounds
WINE_BINARIES = {"wine", "wine64", "wine-preloader", "wine64-preloader"}  # every Proton/Wine game


def app_names(sink_input):
    p = sink_input.proplist
    return {p[k].lower() for k in ("application.process.binary", "application.name") if p.get(k)}


def role(sink_input):
    return sink_input.proplist.get("media.role", "").lower()


def is_event(sink_input):
    return role(sink_input) == "event"


def is_game(sink_input):
    # SDL (most native Linux games) tags its streams with media.role "game" (SDL2) or "Game" (SDL3)
    return role(sink_input) == "game" or bool(app_names(sink_input) & WINE_BINARIES)


def parse(line, cfg):
    try:
        vals = [min(max(int(x) / 1023, 0.0), 1.0) for x in line.strip().split("|")]
    except ValueError:
        return None  # partial/garbled line, common right after connecting
    out = []
    for v in vals:
        v = 1 - v if cfg.invert else v
        v = 0.0 if v < cfg.snap else 1.0 if v > 1 - cfg.snap else v
        out.append(round(v, 3))
    return out


def set_volume(pulse, obj, v):
    try:
        pulse.volume_set_all_chans(obj, v)
    except pulsectl.PulseOperationFailed:
        pass  # stream vanished between listing and setting it


def set_system_volume(pulse, v, cache):
    # Event sounds are often shorter than the re-apply interval, so set the volume
    # pipewire-pulse/PulseAudio gives new ones (pavucontrol's "System Sounds").
    if cache.get("system") == v:
        return  # avoid rewriting the stored entry every re-apply
    entry = next((e for e in pulse.stream_restore_list() if e.name == EVENT_ROLE), None)
    if entry is None:
        entry = pulsectl.PulseExtStreamRestoreInfo(
            EVENT_ROLE, volume=pulsectl.PulseVolumeInfo(v, 2), channel_list=["front-left", "front-right"])
    else:
        entry.volume.value_flat = v
    pulse.stream_restore_write(entry, mode="replace")
    cache["system"] = v


def apply(pulse, values, cfg, cache):
    info = pulse.server_info()
    inputs = pulse.sink_input_list()
    mapped = cfg.mapped_apps
    used = {t for ts in cfg.sliders.values() for t in ts}
    for idx, targets in cfg.sliders.items():
        if idx >= len(values):
            continue
        v = values[idx]
        for t in targets:
            if t == "master":
                set_volume(pulse, pulse.get_sink_by_name(info.default_sink_name), v)
            elif t == "mic":
                set_volume(pulse, pulse.get_source_by_name(info.default_source_name), v)
            elif t == "system":
                set_system_volume(pulse, v, cache)
                for si in inputs:
                    if is_event(si):
                        set_volume(pulse, si, v)
            elif t == "games":
                for si in inputs:
                    if is_game(si) and not app_names(si) & mapped:  # an explicit app mapping wins
                        set_volume(pulse, si, v)
            elif t == "unmapped":
                for si in inputs:
                    if not (app_names(si) & mapped
                            or "system" in used and is_event(si)
                            or "games" in used and is_game(si)):
                        set_volume(pulse, si, v)
            else:
                for si in inputs:
                    if t in app_names(si):
                        set_volume(pulse, si, v)


def changed(new, old, noise):
    return old is None or len(new) != len(old) or any(abs(a - b) > noise for a, b in zip(new, old))


def run(watcher):
    last, last_apply, last_error = None, 0.0, None
    while True:  # reconnect loop: survives unplugging the board, an audio restart, or a port change
        watcher.poll(time.monotonic())
        cfg = watcher.config
        try:
            with serial.Serial(cfg.port, cfg.baud, timeout=1) as ser, pulsectl.Pulse("deej-linux") as pulse:
                log.info("connected to %s", cfg.port)
                last_error, cache = None, {}
                ser.reset_input_buffer()
                while True:
                    new = watcher.poll(time.monotonic())
                    if new:
                        if (new.port, new.baud) != (cfg.port, cfg.baud):
                            log.info("serial settings changed, reconnecting")
                            break
                        cfg, last = new, None  # re-apply right away with the new mapping
                    vals = parse(ser.readline().decode(errors="ignore"), cfg)
                    if not vals:
                        continue
                    if changed(vals, last, cfg.noise) or time.monotonic() - last_apply > cfg.reapply_every:
                        apply(pulse, vals, cfg, cache)
                        last, last_apply = vals, time.monotonic()
        except (serial.SerialException, pulsectl.PulseError, OSError) as e:
            if str(e) != last_error:  # don't flood the log while the board is unplugged
                log.warning("%s - retrying every 2 s", e)
                last_error = str(e)
            last = None
            time.sleep(2)


def list_apps():
    with pulsectl.Pulse("deej-linux") as pulse:
        inputs = pulse.sink_input_list()
        for si in inputs:
            name = ", ".join(sorted(app_names(si))) or f"(unnamed stream #{si.index})"
            tag = "  [system sound]" if is_event(si) else "  [game]" if is_game(si) else ""
            print(name + tag)
        if not inputs:
            print("no apps are playing audio right now")


def main():
    ap = argparse.ArgumentParser(prog="deej-linux", description="deej hardware volume mixer client for Linux")
    ap.add_argument("-c", "--config", default=cfgmod.default_path(),
                    help="config file (default: %(default)s)")
    ap.add_argument("--write-config", action="store_true",
                    help="write the default config to the config path and exit")
    ap.add_argument("--list-apps", action="store_true",
                    help="print the names of apps currently playing audio and exit")
    args = ap.parse_args()

    # under systemd the journal adds its own timestamps
    fmt = "%(levelname)s: %(message)s" if os.environ.get("JOURNAL_STREAM") else "%(asctime)s %(levelname)s: %(message)s"
    logging.basicConfig(level=logging.INFO, format=fmt)

    if args.list_apps:
        list_apps()
        return
    if args.write_config:
        if os.path.exists(args.config):
            sys.exit(f"{args.config} already exists, not overwriting")
        cfgmod.write_default(args.config)
        print(f"wrote {args.config}")
        return

    if not os.path.exists(args.config):
        cfgmod.write_default(args.config)
        log.info("no config found, wrote the default one to %s", args.config)
    try:
        watcher = cfgmod.Watcher(args.config)
    except (cfgmod.ConfigError, OSError) as e:
        sys.exit(f"deej-linux: {e}")
    log.info("using config %s", args.config)
    try:
        run(watcher)
    except KeyboardInterrupt:
        pass

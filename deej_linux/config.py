"""Loading and validating the YAML config (upstream deej's format plus a few extras)."""
import logging
import os
from dataclasses import dataclass, field
from importlib import resources
from pathlib import Path

import yaml

log = logging.getLogger(__name__)

SPECIAL = {"master", "mic", "system", "games", "unmapped"}
ALIASES = {"deej.unmapped": "unmapped", "deej.games": "games"}  # deej.* spelling like upstream
NOISE_LEVELS = {"low": 0.015, "default": 0.025, "high": 0.035}  # same as upstream deej
KNOWN_KEYS = {"slider_mapping", "invert_sliders", "com_port", "baud_rate", "noise_reduction",
              "snap", "reapply_every", "volume_curve"}


class ConfigError(Exception):
    pass


@dataclass(frozen=True)
class Config:
    port: str = "/dev/ttyACM0"
    baud: int = 9600
    invert: bool = False
    noise: float = NOISE_LEVELS["default"]
    snap: float = 0.02
    reapply_every: float = 2.0
    curve: float = 1.0  # volume = slider position ** curve; 1.0 is linear
    sliders: dict = field(default_factory=dict)  # slider index -> list of lowercase targets

    @property
    def mapped_apps(self):
        return {t for ts in self.sliders.values() for t in ts if t not in SPECIAL}


def default_path():
    base = os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config"
    return Path(base) / "deej" / "config.yaml"


def write_default(path):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(resources.files(__package__).joinpath("default_config.yaml").read_text())


def load(path):
    """Read and validate a config file. Raises ConfigError or OSError."""
    try:
        raw = yaml.safe_load(Path(path).read_text()) or {}
    except yaml.YAMLError as e:
        raise ConfigError(f"{path}: invalid YAML: {e}") from e
    if not isinstance(raw, dict):
        raise ConfigError(f"{path}: expected a mapping at the top level")
    return from_dict(raw)


def from_dict(raw):
    for key in raw.keys() - KNOWN_KEYS:
        log.warning("config: ignoring unknown key %r", key)

    sliders = {}
    mapping = raw.get("slider_mapping") or {}
    if not isinstance(mapping, dict):
        raise ConfigError("slider_mapping: expected a mapping of slider index -> targets")
    for key, targets in mapping.items():
        if isinstance(key, bool) or not str(key).isdigit():
            raise ConfigError(f"slider_mapping: {key!r} is not a slider index")
        if targets is None:
            continue
        if isinstance(targets, str):
            targets = [targets]
        if not isinstance(targets, list) or not all(isinstance(t, str) for t in targets):
            raise ConfigError(f"slider_mapping {key}: expected a name or a list of names")
        names = (t.strip().lower() for t in targets)
        sliders[int(key)] = [ALIASES.get(n, n) for n in names if n]

    noise = raw.get("noise_reduction", "default")
    if isinstance(noise, str):
        if noise not in NOISE_LEVELS:
            raise ConfigError(f"noise_reduction: expected one of {', '.join(NOISE_LEVELS)} or a number")
        noise = NOISE_LEVELS[noise]

    return Config(
        port=_get(raw, "com_port", str, Config.port),
        baud=_get(raw, "baud_rate", int, Config.baud),
        invert=_get(raw, "invert_sliders", bool, Config.invert),
        noise=_fraction("noise_reduction", noise),
        snap=_fraction("snap", _get(raw, "snap", float, Config.snap)),
        reapply_every=_get(raw, "reapply_every", float, Config.reapply_every),
        curve=_curve(_get(raw, "volume_curve", float, Config.curve)),
        sliders=sliders,
    )


def _get(raw, key, typ, default):
    value = raw.get(key, default)
    if typ is float and isinstance(value, int) and not isinstance(value, bool):
        value = float(value)
    if not isinstance(value, typ) or (typ is not bool and isinstance(value, bool)):
        raise ConfigError(f"{key}: expected {typ.__name__}, got {value!r}")
    return value


def _fraction(key, value):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not 0 <= value < 0.5:
        raise ConfigError(f"{key}: expected a fraction between 0 and 0.5, got {value!r}")
    return float(value)


def _curve(value):
    if not 0.1 <= value <= 3:
        raise ConfigError(f"volume_curve: expected a number between 0.1 and 3, got {value!r}")
    return value


class Watcher:
    """Holds the current config and reloads it when the file changes."""

    def __init__(self, path, interval=1.0):
        self.path = Path(path)
        self.interval = interval
        self._mtime = self._stat()
        self._next_check = 0.0
        self.config = load(self.path)

    def _stat(self):
        try:
            return self.path.stat().st_mtime_ns
        except OSError:
            return None  # e.g. mid-save by an editor that writes via rename

    def poll(self, now):
        """Return the new Config if the file changed and is valid, else None."""
        if now < self._next_check:
            return None
        self._next_check = now + self.interval
        mtime = self._stat()
        if mtime is None or mtime == self._mtime:
            return None
        self._mtime = mtime
        try:
            self.config = load(self.path)
        except (ConfigError, OSError) as e:
            log.error("config not reloaded, keeping the previous one: %s", e)
            return None
        log.info("config reloaded from %s", self.path)
        return self.config

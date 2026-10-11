# PyDeej

> **Heads-up: this project is vibe coded.** It was written almost entirely by an AI assistant
> (Claude) in conversation with me, then tested on my own hardware and setup. It works for me,
> but the code hasn't had a careful human line-by-line review. Read it before you trust it, and
> expect rough edges.

A minimal Python client for a DIY [deej](https://github.com/omriharel/deej) hardware volume mixer on Linux
(Linux Mint 22+ / PipeWire via `pipewire-pulse`, also works on plain PulseAudio).

The Arduino firmware stays unchanged: it sends `v1|v2|...|vN\n` (values 0–1023) at 9600 baud,
and this client maps each slider to master volume, the mic, specific apps, or "everything else".

## Install (systemd user service)

```bash
git clone https://github.com/oxivanisher/PyDeej.git && cd PyDeej
sudo apt install python3-venv    # if not installed yet
sudo usermod -aG dialout $USER   # serial access; log out and back in afterwards
./install.sh
```

`install.sh` needs no root. It:

- creates a venv in `~/.local/share/deej-linux/venv` and installs the package there
- writes a default config to `~/.config/deej/config.yaml` if none exists
- installs and starts `~/.config/systemd/user/deej-linux.service`, which starts at login

Re-run `./install.sh` after changing the code to update. `./uninstall.sh` removes the service and
venv but keeps your config.

```bash
systemctl --user status deej-linux
journalctl --user -u deej-linux -f
```

## Running from the source tree

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python -m deej_linux              # or: -c some/other/config.yaml
```

## Configuration

`~/.config/deej/config.yaml` uses upstream deej's format, so an existing deej config mostly carries
over. **Changes are applied live.** If you save an invalid file, it is rejected with an error in the
log and the previous config stays active.

| Key | Meaning |
|---|---|
| `slider_mapping` | Slider index → target or list of targets |
| `com_port`, `baud_rate` | Serial port and baud rate (stock sketch: 9600) |
| `invert_sliders` | Flip slider direction |
| `noise_reduction` | Ignore smaller changes: `low` (1.5 %), `default` (2.5 %), `high` (3.5 %), or a fraction like `0.01` |
| `snap` | *(extra)* Snap to exactly 0 % / 100 % within this fraction of either end |
| `reapply_every` | *(extra)* Seconds between re-applying levels, so newly started apps pick them up |

Targets are `master` (default output), `mic` (default input), `system` (system/notification
sounds), `deej.games` (all games, see below), `deej.unmapped` (every app not mapped elsewhere), or an
app name. App names match `application.process.binary` or `application.name`,
case-insensitively. To see what's playing right now:

```bash
~/.local/share/deej-linux/venv/bin/deej-linux --list-apps
```

`system` sets the stored volume for event sounds (pavucontrol's "System Sounds" slider), because
those streams are usually over before the next re-apply. When `system` is mapped, event sounds are
excluded from `deej.unmapped`.

`deej.games` catches games without listing them one by one:

- Proton/Wine games: every Wine process reports the Wine loader (`wine64-preloader`, ...) as its binary
- native Linux games that tag their audio stream with `media.role=game`, which SDL does by default
  (e.g. Factorio)
- anything Steam launches as a game, including non-Steam shortcuts: the process has `SteamGameId` /
  `SteamAppId` in its environment (e.g. Transport Fever 3, which uses neither SDL nor Wine)

`--list-apps` marks matching streams with `[game]`. An app mapped by name to another slider takes
precedence, which helps for a non-game Wine app.

Tip: use a stable port path from `ls /dev/serial/by-id/` instead of `/dev/ttyACM0`. The ttyACM
numbers can swap when several USB serial devices are attached.

## Native PipeWire apps

Upstream deej issue #123 reports that apps outputting to PipeWire *natively* can't be controlled.
On Linux Mint 22 (PipeWire 1.0) they do show up through `pipewire-pulse` and their volume can be
set: verified with Factorio (SDL's pipewire driver). Older PipeWire versions may behave
differently.

## License

MIT, see [LICENSE](LICENSE).

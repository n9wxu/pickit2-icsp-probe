# PICkit 2 ICSP probe

New firmware for the Microchip PICkit 2 that turns it into an open
programming and debug probe for PIC16F1 microcontrollers, with host tools
and OpenOCD support. It is the probe for the
[PIC16F1 open toolchain](https://github.com/n9wxu/pic16f1-toolchain).

| | |
|---|---|
| Programming | Low-voltage (key sequence) and high-voltage (VPP on MCLR) entry. Flash, EEPROM, user IDs, configuration words |
| Debugging | Halt, single step, run, reset, one hardware breakpoint, registers and data memory, using a debug executive written for this project |
| Target power | 1.8–5.0 V from the probe, or self-powered targets |
| Host | USB vendor interface, Python tools, OpenOCD driver |

## Status

Verified on hardware with a PIC16LF1937 on an F1 Evaluation Platform:

- erase, program and verify with both entry methods;
- the debugger functions listed above.

Not verified on hardware: the other devices in the table in
`host/pk2probe.py`, and the whole 8-bit command generation (PIC16F188xx,
PIC16F152xx). Their write latch counts and timings are from memory of the
programming specifications and must be checked against them before use.
Debugging supports the PIC16(L)F193x only.

## Layout

| Path | Content |
|---|---|
| `firmware/` | Probe firmware for the PICkit 2's PIC18F2550 (XC8) |
| `host/pk2boot.py` | Loads firmware through the PICkit 2 bootloader; backup and restore |
| `host/pk2probe.py` | Probe library and programming tool |
| `host/pk2debug.py`, `host/icd16f1.py` | Debugger and the debug executive |
| `host/asm14.py` | Small PIC16F1 assembler used to build the executive |
| `openocd/` | OpenOCD patch, build instructions |
| `docs/protocol.md` | Probe USB protocol |
| `docs/icd.md` | How on-chip debug works on the PIC16(L)F193x |
| `docs/releasing.md` | How a release is made |
| `tools/sds.py` | SCPI helper for a Siglent SDS1000X-E oscilloscope |
| `test/blink/` | Test program for the F1 Evaluation Platform |
| `backup/` | Not in the repository. `pk2boot.py backup` saves your PICkit 2's original firmware here |

## Setup

```sh
python3 -m venv .venv
.venv/bin/pip install -r host/requirements.txt    # libusb itself: brew install libusb
```

The firmware needs MPLAB XC8 and the `PIC18Fxxxx_DFP` device pack. The
`Makefile` has their paths at the top.

```sh
make -C firmware
```

## Loading the firmware

A built `pk2probe-vX.Y.hex` is attached to each
[release](https://github.com/n9wxu/pickit2-icsp-probe/releases); use it in
place of `firmware/build/pk2probe.hex` below if you do not want to build.

The PICkit 2's factory bootloader stays in place and is never written. The
probe firmware is an ordinary application for it, loaded over USB:

```sh
.venv/bin/python host/pk2boot.py backup backup      # once: save the stock firmware
.venv/bin/python host/pk2boot.py flash firmware/build/pk2probe.hex
.venv/bin/python host/pk2boot.py info
```

To go back to the stock firmware, load the backup you made. It is
Microchip's code, so it is kept out of the repository:

```sh
.venv/bin/python host/pk2boot.py flash backup/pickit2_app.hex
```

If the PICkit 2 ever fails to enumerate, hold its button while plugging it
in. That forces the bootloader, and `pk2boot.py flash` works from there.

The firmware is built with a development failsafe (`DEV_FAILSAFE` in
`firmware/main.c`): it returns to the bootloader on a watchdog or stack
reset, and when no host configures it within 20 seconds of power-up. A probe
that must also start on a charger needs `make DEFS=-DDEV_FAILSAFE=0`.

## Programming

```sh
.venv/bin/python host/pk2probe.py --hvp detect
.venv/bin/python host/pk2probe.py --hvp program test/blink/blink.hex
.venv/bin/python host/pk2probe.py read out.hex
.venv/bin/python host/pk2probe.py info
```

Options go before the command. `--vdd MV` sets the target supply (default
3000), `--hvp` selects high-voltage entry, `--no-power` is for targets with
their own supply. Low-voltage entry only works on a part whose `LVP`
configuration bit is set; high-voltage entry always works. The tool refuses a
VDD above the limit of the device it finds.

## Voltage calibration

The PICkit 2 generates and measures voltages relative to its USB supply, so
an uncalibrated unit is a few percent off. `calibrate run` asks for voltmeter
readings at three VDD setpoints and stores factors in the probe's EEPROM, in
the format the stock firmware uses.

```sh
.venv/bin/python host/pk2probe.py calibrate run     # remove 3.3 V targets first
.venv/bin/python host/pk2probe.py calibrate show
```

## Debugging

```sh
.venv/bin/python host/pk2debug.py --vdd 3300 load test/blink/blink.hex
.venv/bin/python host/pk2debug.py step 3
.venv/bin/python host/pk2debug.py cont
.venv/bin/python host/pk2debug.py halt
.venv/bin/python host/pk2debug.py read 70 16
.venv/bin/python host/pk2debug.py unload
```

The limits are in [docs/icd.md](docs/icd.md). The main ones: a breakpoint
stops after its instruction, there is one breakpoint, and the program counter
of a halted target cannot be changed.

A part programmed for debugging does not run without a debugger. `unload`
erases it, including the executive, which an ordinary bulk erase leaves in
place.

## Hardware notes

Measured on one unit with an oscilloscope on the programming connector:

| | |
|---|---|
| VPP | Regulated by a hysteretic boost converter, as in the stock firmware. About 0.2–0.3 V of ripple |
| VPP rise on MCLR | 70 ns, unloaded |
| ICSP clock | 1.0 µs high, 2.75 µs period. Logic levels follow target VDD |
| Read speed | About 9,000 words per second |

The boost converter is fed from the VDD regulator, not from USB. With it
off, the "VPP" level is the VDD setpoint.

## License

MIT, see [LICENSE](LICENSE). The one exception is
`openocd/pk2icsp-pic16f1.patch`: it is a change to OpenOCD and is under
OpenOCD's license, GPL-2.0-or-later.

The probe firmware and host tools contain no Microchip code. The pin
assignments, voltage scaling and debug-link handshake were taken from the
PICkit 2 schematic and from reading Microchip's published PICkit 2 firmware
source as a reference.

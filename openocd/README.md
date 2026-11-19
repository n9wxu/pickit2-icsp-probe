# OpenOCD support for the PICkit 2 ICSP probe and PIC16(L)F193x

This directory holds a patch against OpenOCD v0.12.0 that adds

| Piece | File in the OpenOCD tree |
|---|---|
| Adapter driver `pk2icsp` (USB, 04D8:0033 vendor interface) | `src/jtag/drivers/pk2icsp.c` |
| Transport `icsp`, operation queue, power/programming-mode/debug-link helpers | `src/jtag/icsp.c`, `src/jtag/icsp.h` |
| ICSP programming primitives (6-bit command generation), device table | `src/target/pic16f1_icsp.[ch]` |
| Target `pic16f1` (debug through the on-chip debug executive) | `src/target/pic16f1.c` |
| Debug executive machine code (generated) | `src/target/pic16f1_exec.h` |
| Flash driver `pic16f1` | `src/flash/nor/pic16f1.c` |
| Config files | `tcl/interface/pk2icsp.cfg`, `tcl/target/pic16f193x.cfg` |
| Build integration | `configure.ac` (`--enable-pk2icsp`), `Makefile.am` files |

Files here:

- `pk2icsp-pic16f1.patch`: the patch (`git diff v0.12.0` of the branch `pk2icsp-pic16f1`).
- `gen_pic16f1_exec.py`: generates `src/target/pic16f1_exec.h` from `build_executive()` in `host/icd16f1.py`.
- `openocd-src/`: the OpenOCD clone with the branch checked out and a build in it (git-ignored by the project).

The protocol and debug mechanism are described in `docs/protocol.md` and `docs/icd.md`; the C code is a port of `host/pk2probe.py` (class `Gen6`) and `host/icd16f1.py` (class `Debugger`).

## Build on macOS

```sh
brew install autoconf automake libtool pkg-config texinfo libusb   # once
git clone https://github.com/openocd-org/openocd.git openocd-src   # or use a v0.12.0 tarball/clone
cd openocd-src
git checkout v0.12.0
git submodule update --init jimtcl                                  # the bundled Tcl
git apply ../pk2icsp-pic16f1.patch
SKIP_SUBMODULE=1 ./bootstrap        # no network needed (jimtcl was fetched above)
export PKG_CONFIG_PATH="$(brew --prefix libusb)/lib/pkgconfig"
./configure --enable-pk2icsp --disable-werror --disable-jlink --disable-internal-libjaylink
make -j8
```

Run from the build tree, no install needed: `src/openocd -s tcl -f interface/pk2icsp.cfg -f target/pic16f193x.cfg`.
(Do not install over another OpenOCD.) Other adapters are built too if their libraries are found; add
`--disable-<name>` for those you do not want.

Regenerating the executive header (only needed if `host/icd16f1.py` changes; needs pyusb because that module imports `pk2probe`):

```sh
python3 openocd/gen_pic16f1_exec.py > openocd/openocd-src/src/target/pic16f1_exec.h
```

## Running

```sh
src/openocd -s tcl -f interface/pk2icsp.cfg \
    -c "pk2icsp vdd 3300" -c "pk2icsp hvp on" \
    -f target/pic16f193x.cfg
```

This starts Tcl (6666), telnet (4444) and gdb (3333) servers. Settings must be given between the two config files
(or before `init`). Defaults are VDD 3000 mV, the probe powers the target, low-voltage entry.

### Adapter commands (`pk2icsp`)

| Command | Meaning |
|---|---|
| `pk2icsp vdd [mV]` | Target VDD setpoint, 1800 to 5000, default 3000. Values above 5000 are refused. The part's own maximum (3600 mV for PIC16LF) is checked when the device is identified: a higher setpoint is refused for programming. |
| `pk2icsp power [on\|off]` | `on` (default): the probe supplies the target. `off`: self-powered target, VDD is not touched. |
| `pk2icsp hvp [on\|off]` | Enter programming mode with VPP on MCLR (works whatever the configuration words say). Default `off`: low-voltage key sequence, which needs LVP enabled in the target (worked once on the test target, which has LVP on; all other runs used `hvp on`). |
| `pk2icsp vpp [mV]` | VPP for `hvp on`, 5000 to 13000, default 8500. |
| `pk2icsp power_off_on_quit [on\|off]` | Switch target power off when OpenOCD exits. Default `off`: power stays on, so the debug session survives. |
| `pk2icsp status` | Power flags and voltages. |

On start the probe switches the target on at the setpoint unless it is already on. On exit the pins and MCLR are
released and the boost converter stopped; target power is left on unless `power_off_on_quit on`.

### Target commands

| Command | Meaning |
|---|---|
| `pic16f1 load_debug <hex>` | What `Debugger.load` does: bulk erase, program flash/EEPROM/user IDs of the image, the debug executive (0x8004, 0x8010-0x8088), configuration words with DEBUG enabled, verify, release reset. The target ends halted at the reset vector. |
| `pic16f1 unload_debug` | What `Debugger.unload` does: bulk erase and erase the executive rows 0x8020-0x80FF. The device is blank afterwards (it keeps running, power stays on). |

Standard commands that work: `halt`, `resume`, `step`, `reset halt|run|init`, `reg`, `reg <name> [value]`, `bp <addr> 2 hw`,
`rbp`, `mdb/mdh/mdw/mwb/...`, `targets`, `poll`, and over gdb-remote the generic register and memory packets.

### Registers

`pc`, `w`, `status`, `bsr`, `pclath`, `fsr0`, `fsr1`, `stkptr` (all read while halted). All can be written except
`pc`, which fails with `the program counter of a halted target cannot be changed` (the hardware has no way to set it).
The register values are cached on every halt (about 120 ms for the batch of reads).

### Address convention

- **Code addresses are byte addresses as in HEX files**: byte address = 2 x word address. Program flash is at 0.
  The `pc` register, `bp` addresses and the flash banks all use it. Word 0x7F8 is byte 0xFF0. (The Python tools print word PCs.)
- **Data memory is at 0x800000 + address**, where address is the CPU's register-file address 0x000-0xFFF
  (bank x 0x80 + offset) or a linear address 0x2000 and up. Core registers are translated to where the executive keeps
  the user's values exactly as `Debugger._map/read_data/write_data` do (`STATUS`, `PCL`, `FSR`, `BSR`, `W`).
  Example: `mdb 0x800070 2` reads RAM 0x70-0x71; `mdb 0x80010f 2` reads LATD/LATE.
- **Program memory cannot be read during a debug session** (reads below 0x800000 fail with an explanatory error).
  `flash read_bank` and `flash verify_image` can: they use a programming session, which resets the target (see below).
- Data memory accesses are one byte per executive command (about 2.5 ms per byte over the link, batched in the probe).

### Breakpoint skid

There is exactly one hardware breakpoint. **The target halts after the instruction at the breakpoint address has executed**,
so the reported pc is the next instruction to execute (the branch target if the instruction at the address was a jump).
A breakpoint at the current pc therefore lets one instruction run. Single step uses the same breakpoint, so a step
temporarily replaces the user breakpoint, which is re-armed at the next `resume`. Only hardware breakpoints are accepted
(`bp <addr> 2 hw`); the config file sets `gdb_breakpoint_override hard` so that gdb's software breakpoint requests
use the hardware one. Watchpoints are not available. `resume <address>` and `step <address>` fail, as the pc cannot be changed.

### Flash banks

`target/pic16f193x.cfg` defines three banks, selected by their base address (HEX byte address):

| Bank | Base | Content |
|---|---|---|
| `<chip>.flash` | 0x00000 | program flash, size set by the probe (2 x words) |
| `<chip>.config` | 0x10000 | user IDs (word 0x8000-0x8003) and configuration words (0x8007-0x8008) |
| `<chip>.eeprom` | 0x1E000 | data EEPROM, one byte per 16 bit word (HEX word address 0xF000+), data in the low byte |

- The sector is the whole bank. **Erasing the flash bank (`flash erase_sector 0 0 0`, `erase_address`, `write_image erase`) is a bulk
  erase of the whole device**: program memory, user IDs, configuration words and data EEPROM. Calibration words survive.
- Erasing the EEPROM bank erases the data EEPROM only. The config bank cannot be erased on its own; erasing it does nothing
  (it is erased by the flash bank, which comes first in an image).
- `flash write_image erase file.hex` writes program memory (skipping blank 8-word latches), EEPROM and user IDs, then
  the configuration words last, and **reads everything back over ICSP to verify it**. A mismatch fails the command.
- `flash verify_image file.hex` and `flash read_bank` read back over ICSP. (`flash verify_bank` compares with a binary file.)
- `flash erase_check` reads the bank over ICSP.
- An image that enables DEBUG (configuration word 2 bit 12 = 0) is refused by the flash driver; use `pic16f1 load_debug`.
- Device detection is from the device ID (table in `src/target/pic16f1_icsp.c`, same as `host/pk2probe.py`): PIC16(L)F1933/34/36/37/38/39
  (debug supported), and PIC16F1829/PIC16F1619 with the 6-bit command set (listed, **not tried**).
- Every flash operation enters programming mode, **which resets the target** (with `hvp on` and probe power it is power cycled), and
  leaves the target running with its power on. A debug session is lost: the target driver forgets its state and the next
  poll finds the target running, halted at its reset breakpoint, or not responding. Re-run `pic16f1 load_debug` for a plain
  re-program with debugging.

## Example session (real output, PIC16LF1937 on the F1 Evaluation Platform)

```
$ src/openocd -s tcl -f interface/pk2icsp.cfg -c "pk2icsp vdd 3300" -c "pk2icsp hvp on" -f target/pic16f193x.cfg
Info : pk2icsp: probe firmware 0.1, protocol 1, capabilities 0x1f
Info : icsp: target VDD 3284 mV
Info : pic16f1: debug link ready, target halted
Info : Listening on port 4444 for telnet connections

> flash probe 0
flash 'pic16f1' found at 0x00000000      (log: Info : pic16f1: PIC16LF1937, device ID 0x2480, revision 2, 8192 words of flash, 256 bytes of EEPROM)
> flash write_image erase test/blink/blink.hex
wrote 5170 bytes from file test/blink/blink.hex in 1.226378s (4.117 KiB/s)
> flash verify_image test/blink/blink.hex
verified 5170 bytes from file test/blink/blink.hex in 0.558765s (9.036 KiB/s)
> pic16f1 load_debug test/blink/blink.hex
target programmed for debugging, state: halted
> reg
(0) pc (/16): 0x0002
(1) w (/8): 0x00
...
> step
> reg pc
pc (/16): 0x0004
> resume
> halt
> reg pc
pc (/16): 0x0ff0
> bp 0xff2 2 hw
> resume
> mdb 0x800070 4
0x00800070: 52 00 01 01
> mwb 0x800070 0xA5
> reset halt
```

## Limitations

- Only the PIC16(L)F193x are supported for debugging, and only one device, a PIC16LF1937 revision 2, was tried.
  PIC16F1829/1619 are in the table, untried. The 8-bit command generation (PIC16F1xxxx) is not supported.
- One hardware breakpoint; it halts after the instruction. No software breakpoints (the pc cannot be changed, so they
  cannot be made transparent), no watchpoints.
- The pc cannot be written. `resume`/`step` at an address fail.
- Program memory cannot be read while debugging (use a programming session); `verify_image` (target command) and
  `dump_image` of code addresses do not work, use `flash verify_image` / `flash read_bank`.
- Erase is a bulk erase of the whole device (no sector or row erase). Config words can only be rewritten after a bulk erase.
- Programming mode entry resets the target and ends any debug session. The device is not code-protected-aware: with code protection
  enabled reads return zeros and verification fails.
- `reset` resumes the target and then pulses MCLR. If MCLR is configured as a digital input (MCLRE = 0) the
  pulse has no effect and the target is power cycled instead, which needs `pk2icsp power on`. A self-powered
  target with MCLRE = 0 cannot be reset.
- Register and memory access over the executive link is slow (about 10 ms per byte read); registers are read once per halt.
- The USB device is found by VID:PID and the vendor interface class; the stock PICkit 2 firmware (HID) is not usable.
  Only one probe is expected (`adapter serial` is honoured but not tested).
- Tested only on macOS (Apple Silicon, libusb 1.0.30). Not tested: `pk2icsp power off` (self-powered target),
  `power_off_on_quit on`, VDD above 3300 mV, other host OSes.
- Only the C style checks that the build performs were run (no uncrustify/checkpatch).

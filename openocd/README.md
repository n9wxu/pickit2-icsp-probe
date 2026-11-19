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
| `pic16f1 load_debug <file> [type]` | Intel HEX or ELF, detected from the file. What `Debugger.load` does: bulk erase, program flash/EEPROM/user IDs of the image, the debug executive (0x8004, 0x8010-0x8088), configuration words with DEBUG enabled, verify, release reset. The target ends halted at the reset vector. |
| `pic16f1 unload_debug` | What `Debugger.unload` does: bulk erase and erase the executive rows 0x8020-0x80FF. The device is blank afterwards (it keeps running, power stays on). |

| `pic16f1 forget_flash` | Drop the program memory read so far in this session. Only needed after the program has written its own flash. |

Standard commands that work: `halt`, `resume`, `step`, `reset halt|run|init`, `reg`, `reg <name> [value]`, `bp <addr> 2 hw`,
`rbp`, `mdb/mdh/mdw/mwb/...`, `targets`, `poll`, and over gdb-remote the generic register and memory packets.

### Registers

In `g` packet order, as agreed with the toolchain's LLDB work:

| Number | Name | Bits | Content |
|---|---|---|---|
| 0 | `pc` | 32 | Byte address of the next instruction (2 x word PC). Read only |
| 1-4 | `w`, `status`, `bsr`, `pclath` | 8 | |
| 5, 6 | `fsr0`, `fsr1` | 16 | |
| 7 | `stkptr` | 8 | 0x1F when the return stack is empty |
| 8-21 | `r0`-`r13` | 8 | Common RAM 0x70-0x7D, the compiler's registers |
| 22, 23 | `tmp0`, `tmp1` | 8 | Common RAM 0x7E, 0x7F |

All can be written except `pc`: the hardware has no way to set it, and the write fails with an error (over gdb-remote
too, an `E` reply to `P`). The values are read once on every halt, 27 bytes in one batch.

### Address convention

- **Code addresses are byte addresses as in HEX files**: byte address = 2 x word address. Program flash is at 0.
  The `pc` register, `bp` addresses and the flash banks all use it. Word 0x7F8 is byte 0xFF0. (The Python tools print word PCs.)
- **Data memory is at 0x800000 + address**, where address is the CPU's register-file address 0x000-0xFFF
  (bank x 0x80 + offset) or a linear address 0x2000 and up. Core registers are translated to where the executive keeps
  the user's values exactly as `Debugger._map/read_data/write_data` do (`STATUS`, `PCL`, `FSR`, `BSR`, `W`).
  Example: `mdb 0x800070 2` reads RAM 0x70-0x71; `mdb 0x80010f 2` reads LATD/LATE.
- **Flash through the data space**: 0x808000 and up is program memory as an FSR sees it, the low 8 bits of each word,
  one byte per word.
- **The hardware return stack is at 0x810000**: 16 slots of two bytes, little endian, slot `n` at 0x810000 + 2n. Each
  holds the word address the silicon keeps (not doubled). Slot `stkptr` is the top of the stack. Read only. Reads
  past the 32 bytes return zeros, because a debugger's memory cache reads more than it was asked for.
- **Program memory can be read from a halted target** at its code address, two bytes per word. So can the configuration
  space at 0x10000 (user IDs, device ID at 0x1000C, configuration words at 0x1000E) and the data EEPROM at 0x1E000
  (one word per byte). The driver has the part read its own memory through `EEADR`/`EECON1`/`EEDAT` and puts the
  user's values of those registers back. Words read are kept until the part is reprogrammed or contact is lost
  (`pic16f1 forget_flash` drops them). The executive's own words at 0x8010 and up read as zero this way. None of
  this can be written during a debug session.
- Data memory accesses are one byte per executive command. See "Speed" below.

### What a debugger sees over gdb-remote

Checked with raw packets on the PIC16LF1937 (the list the toolchain's LLDB plugin will use): `qSupported`,
`qXfer:features:read` (target.xml, feature `org.gnu.gdb.pic16f1.core`), `qXfer:memory-map:read`, `?`, `g`, `p`/`P`,
`m`/`M`, `c`, `s`, `vCont` with `c` and `s`, `Z`/`z`, interrupt (0x03), `D`.

- Connecting halts the target (`gdb-attach` event in the config file). Probing the flash banks for the memory map
  goes through the debug link when the target is halted, so connecting does not reset it.
- `Z0` and `Z1` both use the one hardware breakpoint. A second breakpoint gets an `E` reply.
- A stop is reported with the true pc: after a breakpoint that is the instruction after the breakpoint address.
- There is no thread list (`qfThreadInfo` answers `l`) and no `qHostInfo`; stop replies are `T05` without a thread.

### LLDB from the PIC16F1 toolchain

Tried on the PIC16LF1937 with the toolchain's `examples/debug/main.c`, with configuration words added
(`PIC_CONFIG_WORDS(0x09C4, 0x3EFF);`; the toolchain ignores `#pragma config`, and a part with erased configuration
words expects an external clock and does not run):

```sh
pic16f1-cc -g -O1 -mcpu=pic16f1937 -o prog.hex main.c         # leaves prog.elf beside it
src/openocd -s tcl -f interface/pk2icsp.cfg -c "pk2icsp vdd 3300" -c "pk2icsp hvp on" \
    -f target/pic16f193x.cfg -c "init; pic16f1 load_debug prog.elf"
pic16f1-lldb prog.elf -o "gdb-remote 3333"
```

What worked: connecting, the register display including the compiler's pairs, disassembly, breakpoints by function
name and by source line, `continue`, `stepi`, `bt` through inlined frames and a library routine, `frame variable`,
`target variable`, expressions (`p gain + gain + total`) and assignment (`expr gain = 6`, read back through OpenOCD).
Run to the last line, `total` read 83, the value the program is written to end with. `bt` inside the recursive
function lists all five frames.

What did not, all on the debugger's side and reported to the toolchain project:

- LLDB reads memory in 512-byte lines by default, which made the first disassembly take 14 s at this board's
  500 kHz clock. The toolchain's `pic16f1-lldb` now sets a 32-byte line; a whole session then took 6 s.
- `next` over a call, with a user breakpoint set, stopped inside the called routine: it needs a second breakpoint.
- A stop at a breakpoint is shown as `signal SIGTRAP` one instruction on, not as a breakpoint hit.

### Speed

The link is clocked by the target, so it follows the target's oscillator. Measured on the test board at 500 kHz
(the part's default internal oscillator), where one instruction takes 8 us:

| Operation | Time |
|---|---|
| Halt and read all registers | 300 ms |
| Single step, registers read | 325 ms |
| Read 16 bytes of data memory | 175 ms (11 ms per byte) |
| Read program memory, first time | 55 ms per word |
| Read the return stack | 550 ms |

A program that switches to a faster oscillator shortens the bit times in proportion; an 800 us handshake per byte
remains, which sets a floor near 3 ms per byte of data memory.

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
(0) pc (/32): 0x00000002
(1) w (/8): 0x00
...
> step
> reg pc
pc (/32): 0x00000004
> resume
> halt
> reg pc
pc (/32): 0x00000ff0
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
- Program memory is read-only while debugging, and slow to read at a low target clock (see "Speed").
- ELF input to `load_debug` was tried with one file from the PIC16F1 toolchain. Data whose load address is in
  0x808000 and up is programmed as `RETLW` words, as that toolchain's HEX conversion does; RAM sections are skipped.
- **A target in `SLEEP` cannot be halted.** `reset` then power cycles it, which needs `pk2icsp power on`. A
  breakpoint before the `SLEEP` is the way to stop a program that ends that way.
- Erase is a bulk erase of the whole device (no sector or row erase). Config words can only be rewritten after a bulk erase.
- Programming mode entry resets the target and ends any debug session. The device is not code-protected-aware: with code protection
  enabled reads return zeros and verification fails.
- `reset` halts the target, resumes it and then pulses MCLR. If MCLR is configured as a digital input (MCLRE = 0) the
  pulse has no effect and the target is power cycled instead, which needs `pk2icsp power on`. A self-powered
  target with MCLRE = 0 cannot be reset.
- Register and memory access over the executive link is slow at a low target clock (see "Speed").
- The USB device is found by VID:PID and the vendor interface class; the stock PICkit 2 firmware (HID) is not usable.
  Only one probe is expected (`adapter serial` is honoured but not tested).
- Tested only on macOS (Apple Silicon, libusb 1.0.30). Not tested: `pk2icsp power off` (self-powered target),
  `power_off_on_quit on`, VDD above 3300 mV, other host OSes.
- Only the C style checks that the build performs were run (no uncrustify/checkpatch).

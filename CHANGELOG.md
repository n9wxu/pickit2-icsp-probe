# Changelog

## Unreleased

## v0.1 (2026-11-20)

Firmware 0.1, protocol 1. Verified on a PIC16LF1937 only.

- Probe firmware for the PICkit 2, loaded through its factory bootloader.
- Programming of PIC16(L)F193x with low-voltage and high-voltage entry.
- Debugging of PIC16(L)F193x with an independent debug executive: halt,
  step, run, reset, one hardware breakpoint, registers, data memory.
- OpenOCD 0.12.0 patch: `pk2icsp` adapter, `icsp` transport, `pic16f1`
  target and flash driver.
- OpenOCD target, for source-level debugging with the toolchain's LLDB:
  program memory, configuration space and EEPROM readable from a halted
  target; hardware return stack at 0x810000; registers `r0`-`r13`, `tmp0`,
  `tmp1`; 32-bit `pc`; connecting a debugger halts the target without
  resetting it; `load_debug` takes the toolchain's ELF files. A session
  with the toolchain's LLDB ran on the PIC16LF1937.
- Software breakpoints, in the Python debugger (`pk2debug.py break`,
  `clear`) and the OpenOCD target (`bp <addr> 2`, a debugger's `Z0`): any
  number, stopping before the instruction. The instruction is replaced in
  flash by a call to a two-word gadget placed at load time, and the
  debugger does the work of the replaced instruction itself when the target
  goes on. The emulation was compared with the part instruction by
  instruction. The toolchain's LLDB now shows breakpoint hits as such, and
  `next` works with user breakpoints set.
- The debug executive has a fourth command, which runs the flash unlock
  sequence, so the part can rewrite a row of its own flash during a
  session.

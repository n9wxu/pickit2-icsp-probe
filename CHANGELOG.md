# Changelog

## Unreleased

Firmware 0.1, protocol 1. Verified on a PIC16LF1937 only.

- Probe firmware for the PICkit 2, loaded through its factory bootloader.
- Programming of PIC16(L)F193x with low-voltage and high-voltage entry.
- Debugging of PIC16(L)F193x with an independent debug executive: halt,
  step, run, reset, one hardware breakpoint, registers, data memory.
- OpenOCD 0.12.0 patch: `pk2icsp` adapter, `icsp` transport, `pic16f1`
  target and flash driver.

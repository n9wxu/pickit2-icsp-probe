# On-chip debug of the PIC16(L)F193x

Microchip does not publish how in-circuit debugging works on these parts.
Everything here was established by experiment on one PIC16LF1937 (revision
2, on an F1 Evaluation Platform), using test code written for the purpose
and the probe as the observer. No Microchip debug executive was read,
disassembled or captured. The published inputs were:

- the device family pack, which gives the debug vector address (0x8004),
  the RAM reserved for a debugger (0x320–0x32F) and register and bit *names*
  for the debug-header variant of the chip;
- the PICkit 2 firmware source, which shows the handshake a debug executive
  uses to talk to the probe.

Other PIC16F1 parts are likely to be similar but have not been tried.

## The debug program space

With the `DEBUG` configuration bit programmed to 0, the core has a second
program space that is separate from user flash.

| Address | Content |
|---|---|
| 0x8000–0x8003 | User IDs |
| 0x8004 | Debug vector: the first instruction executed on debug entry |
| 0x8005 | Writable, unused |
| 0x8006 | Device ID |
| 0x8007–0x8008 | Configuration words |
| 0x8009–0x800A | Calibration words (survive a bulk erase) |
| 0x800B–0x80FF | Writable. The debug executive goes in 0x8010–0x80FF (240 words) |
| 0x8100–0x81FF | Factory content, write protected. Not used or examined |

The space is 512 words and repeats every 0x200 up to 0xFFFF. `GOTO` and
`CALL` executed there stay there, whatever `PCLATH` holds, and because of the
repetition they reach the same code for any `PCLATH`. `CALL` and `RETURN`
work, at least one level deep, and do not use the user's stack (`STKPTR` does
not change).

Programming uses the ordinary ICSP commands with the address counter in
configuration space, one word per write.

- 0x8004–0x801F are erased by a bulk erase with the address in configuration
  space.
- 0x8020–0x80FF are **not** erased by a bulk erase. They need a row erase
  (command 0x11) with the address in the row; rows are 32 words.
- Writes to 0x8100 and above are ignored.

With `DEBUG` enabled and nothing usable at the vector, the part does not run
user code. Always erase the executive rows when removing debug support.

## Entering debug mode

The core jumps to the debug vector in three cases.

| Cause | Behaviour |
|---|---|
| Hardware breakpoint | After the instruction at the breakpoint address has executed |
| Opcode 0x0002 or 0x0003 | After that instruction. These are software breakpoints |
| ICSPCLK driven high while user code runs | Within a few instructions. ICSPDAT alone has no effect |

In all cases the reported PC is the next instruction to execute. A breakpoint
therefore stops *after* its instruction, not before it.

A power-on reset enables the hardware breakpoint at address 0, so a freshly
powered target stops with PC = 1, having executed the instruction at the
reset vector. Put a `NOP` or a `GOTO` there.

An MCLR reset has no effect while the core is in debug mode. While user code
runs it resets the part as usual, and the breakpoint register keeps its
value across it.

## Registers in debug mode

These are in bank 31 and read as zero in user mode. Their addresses differ
from the debug-header definitions in the device pack.

| Address | Function |
|---|---|
| 0xF8C | Debug pins. Bit 7 ICSPDAT, bit 6 ICSPCLK: write sets the output level, read gives the pin. Bit 3 ICSPDAT direction, bit 2 ICSPCLK direction (1 = input). The state persists while user code runs |
| 0xF8D | Reads back the same output latches and direction bits |
| 0xF8E | Bit 7 reads 1 in debug mode and cannot be written. Bits 6 and 5 are writable; their effect was not investigated |
| 0xF90 | Read: PC at the halt, low byte. Write: breakpoint address, low byte |
| 0xF91 | Same, high 7 bits. Bit 7 enables the breakpoint |
| 0xFE3 | The user's BSR, saved on entry and restored on return |

After any halt, 0xF91:0xF90 holds the current PC and keeps its enable bit.
Returning with the bit still set makes the breakpoint match the current
instruction, so exactly one instruction runs. That is the single step.

Writing 0xF91:0xF90 sets the breakpoint only. It does not change where
execution resumes, and no way of changing the PC of a halted target was
found.

`W`, `STATUS`, `PCLATH` and the FSRs are not saved by the hardware. `BSR` is.

## Leaving debug mode

Opcode 0x0004 returns to user code at the point where it stopped. Of the
other unassigned opcodes, 0x0005–0x0007, 0x000C–0x000F, 0x0060 and 0x0061
behave as `NOP`, in both modes. `RETURN` and `RETFIE` do not leave the debug
space usefully.

## The debug executive

`host/icd16f1.py` builds the executive with the small assembler in
`host/asm14.py`. It is 120 words.

On entry it selects bank 6, stores `W`, reads `STATUS` with `SWAPF` (which
changes no flags) and stores the FSRs, all in 0x320–0x325. It then points
`FSR1` at the pin register and serves commands. Each byte uses the handshake
described in `firmware/icsp.c`: the target raises the clock, the probe pulses
data low, and the target then clocks eight bits.

| Command | Bytes from the host | Reply |
|---|---|---|
| Read | 0x01, address low, address high | The byte read through `FSR0` |
| Write | 0x02, address low, address high, value | None |
| Resume | 0x03 | None. Registers are restored and opcode 0x0004 runs |

The host does the rest by reading and writing memory.

| To do this | The host |
|---|---|
| Read `W`, `STATUS`, `FSR0`, `FSR1` | Reads 0x320, 0x321 (nibbles swapped), 0x322–0x325 |
| Read `BSR`, `PCLATH`, the PC | Reads 0xFE3, 0x00A, 0xF90 and 0xF91 |
| Single step | Writes the current PC with bit 15 set to 0xF91:0xF90, then resumes |
| Run to a breakpoint | Writes the address with bit 15 set, then resumes |
| Run freely | Clears bit 7 of 0xF91, then resumes |
| Halt | Drives ICSPCLK high for 200 µs, then releases it |
| Reset | Sets the breakpoint to address 0, resumes, pulses MCLR |

## Limits

- One hardware breakpoint, which the single step also uses.
- Breakpoints stop one instruction late.
- The PC cannot be changed, so software breakpoints cannot be made
  transparent: after the trap there is no way to go back and execute the
  instruction it replaced.
- Program memory is not read from the target during a session. The host
  keeps the image it programmed.
- The executive needs about 2.5 ms per byte at the 500 kHz reset clock, so a
  register read takes about 10 ms.
- `DEBUG` enabled means ICSPCLK and ICSPDAT belong to the debugger.

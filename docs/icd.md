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
| 0xF8E | Bit 7 reads 1 in debug mode and cannot be written. Bit 5 is a single step: with it set, a resume executes one instruction and comes back, without using the breakpoint. Bit 6 is writable; no effect was seen |
| 0xF90 | Read: PC at the halt, low byte. Write: breakpoint address, low byte |
| 0xF91 | Same, high 7 bits. Bit 7 enables the breakpoint |
| 0xFE3 | The user's BSR, saved on entry and restored on return |

After any halt, 0xF91:0xF90 holds the current PC and keeps its enable bit.
Returning with the bit still set makes the breakpoint match the current
instruction, so exactly one instruction runs. That is the single step.

Writing 0xF91:0xF90 sets the breakpoint only. It does not change where
execution resumes, and no way of changing the PC of a halted target was
found.

No other debug register exists in the data space. Every address that the
production register map leaves undocumented reads zero in debug mode and
ignores writes, apart from the ones in this table (D9, D10). In particular
there is no register for handing the core an instruction to execute, which
the debug-header variant's `ICDINST` and `DBGINEX` names describe.

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
- The PC cannot be changed. After a software breakpoint the PC is already
  past it, so the instruction it replaced cannot be re-run from flash. It
  would have to be carried out some other way; see "Software breakpoints"
  below. The debugger does not implement them.
- The single-step bit in 0xF8E is not used yet. Stepping still borrows the
  hardware breakpoint.
- Program memory can be read from a halted target but not written (D13).
  The Python debugger still answers from the image it programmed; the
  OpenOCD target reads the part.
- The executive needs about 2.5 ms per byte at the 500 kHz reset clock, so a
  register read takes about 10 ms.
- `DEBUG` enabled means ICSPCLK and ICSPDAT belong to the debugger.
- A target that has executed `SLEEP` does not answer the halt request. An
  MCLR pulse with ICSPCLK held high across its release did not stop it
  either. A power cycle does.

# Development record

The rest of this document is the record of how the facts above were found:
each experiment, what it was meant to decide, what came back, and what was
concluded, including the wrong turns. All of it was done on 2026-11-18 on
one PIC16LF1937, revision 2 (device ID word 0x2482), on an F1 Evaluation
Platform powered by the probe at 3.3 V.

The scripts are kept in `experiments/icd/` as they were run. They are a
record, not maintained code: some call functions that were later changed or
removed.

## Starting point and ground rules

What was known before the first experiment:

| Source | Fact |
|---|---|
| Device pack, `PIC16F1937.PIC` | `BACKBUGVectorSector` at 0x8004–0x8005. One hardware breakpoint. `DEBUG` is bit 12 of CONFIG2, 0 = enabled |
| Device pack, XC8 `16f1937.ini` | `ICD3RAM=320-32F`. No program memory range is reserved for a debugger, for any part in the pack |
| Device pack, `AC244055_AS_PIC16F1937.PIC` (the debug-header variant) | Names and addresses of hidden registers: `ICDIO` 0xF8C, `ICDCON0` 0xF8D, `ICDSTAT` 0xF91, `ICDINSTL/H` 0xF96/7, `ICDBK0CON` 0xF9C, `ICDBK0L/H` 0xF9D/E, `BSRICDSHAD` 0xFE3, with bit names such as `INBUG`, `FREEZ`, `SSTEP`, `TRP0HLTF`, `TRP1HLTF`, `USRHLTF` |
| PICkit 2 firmware source v2.32, `ICDSlave_transmit`, `ICDSlave_Receive` | The debug executive drives the clock; the probe answers a handshake and follows |

The header-variant register addresses turned out to be wrong for the
production part, as the experiments show. The names were still a useful
guide to what should exist.

Rules followed throughout:

- No Microchip debug executive was obtained, read or captured. The PICkit 3
  was never used. MPLAB X is not installed on the machine.
- The factory content found at 0x8120 and above was not disassembled or
  analysed. One thing was noted from its raw words, before the decision to
  leave it alone: its `GOTO` targets are small numbers, which suggested that
  jumps stay inside the 0x8xxx space.
- Writes to reserved memory were made only after asking the owner of the
  board, one cell at a time, and reversed. The configuration space was read
  back and compared with a saved copy after each round.

## Observation channels

The probe can see only ICSPCLK, ICSPDAT, MCLR and VDD. Three ways of getting
information out of the target were used, in this order.

| Channel | How | Limits |
|---|---|---|
| Pin states | Test code drives ICSPCLK or ICSPDAT; the probe reads them | Needs the pin register to be understood first |
| EEPROM log | Test code writes bytes to the data EEPROM; the probe reads the EEPROM back over ICSP | Works in user code. Never produced output from debug mode (E2) |
| RAM persistence | Test code writes to RAM. Without dropping VDD, the part is reprogrammed with a "dumper" that copies RAM to EEPROM, which is then read over ICSP | Slow (about 10 s per run) but independent of everything under test. RAM survives MCLR and programming mode as long as VDD is held |

The RAM channel needs three programs per run: one with `DEBUG` off that
zeroes a RAM area, the program under test, and the dumper. Reprogramming in
between uses low-voltage entry, which does not interrupt power. `Lab` in
`experiments/icd/icdx.py` does this.

Once the executive could talk over the debug link (D1), the experiments
became interactive and the RAM channel was no longer needed.

## Tooling

A small assembler, `host/asm14.py`, was written so that arbitrary words,
including unassigned opcodes, could be placed at exact addresses including
0x8004. Test images were built in Python and programmed with the probe's
ordinary ICSP functions.

## Phase 1: what does the DEBUG bit do

### E0. Is the debug vector writable

`e0.py`. Read 0x8000–0x800F, wrote 0x2ABC to 0x8004 with a normal
configuration-space write, read back.

Result: 0x8004 read 0x2ABC. The calibration words are at 0x8009–0x800A.

### E1. Does an executive in user flash announce itself

`e1.py`. `DEBUG` enabled. `GOTO 0x700` at the vector. An executive at
0x0700 in each of the four flash pages (in case `PCLATH` mattered) that
tries to send bytes over the debug link using the header-variant `ICDIO`
bit layout.

Result: nothing. Both pins stayed low.

This could mean the executive did not run, or that the pin register does not
work as assumed. A channel independent of the pins was needed.

### E2. EEPROM log, DEBUG off and on

`e2.py`. User code logs a marker and the hidden registers to EEPROM, then
tries to drive the pins. The executive copies log their own markers.

| | Result |
|---|---|
| `DEBUG` off | User code ran. `ICDCON0`, `ICDSTAT`, `ICDIO` read 0 and could not be written. RB7 worked as a port pin |
| `DEBUG` on | Nothing was logged at all, by user code or by any executive copy |

Conclusion: the hidden registers are not accessible in user mode, and with
`DEBUG` on the core does not start user code after reset. Whether the
executive ran was still open, because an EEPROM write might not complete in
debug mode.

### E3. RAM persistence, DEBUG off and on

`e3.py`. Same question, with RAM as the witness.

| | 0x120 (user marker) | 0x121 (user counter) | Executive log |
|---|---|---|---|
| `DEBUG` off | 0x55 | 0x51 | empty |
| `DEBUG` on | 0x00 | 0x00 | empty |

Conclusion: with `DEBUG` on, neither user code nor code at 0x0700 in any
page executes. The control run also proved the RAM channel.

## Phase 2: where does the vector lead

### E4. Device files, and a map of the configuration space

`e4.py`. Two checks.

The XC8 `.ini` files in the pack contain no `ICDnROM` range for any device,
only `ICD3RAM`. So Microchip's executive does not occupy user flash on this
family.

Read 0x8000–0x83FF. Besides the documented words there were 190 non-blank
cells, starting at 0x8120. That is the factory content.

The same script wrote 0x1555 to 0x8005, 0x800B and 0x800F to see whether
they are writable. They are. In hindsight this was done too casually: these
are reserved cells and it was not yet known that an erase would restore
them.

### E5. Does a bulk erase restore those cells

`e5.py`. Bulk erase with the address in configuration space, then read
0x8000–0x83FF.

Result: 0x8005, 0x800B and 0x800F were back to 0x3FFF. The count of
non-blank cells and a checksum of 0x8100–0x83FF (0xE268) matched the first
read. The checksum was kept as a guard for later rounds.

### E6. Which instructions at the vector reach user flash

`e6.py`. RAM channel. Five choices for the words at 0x8004 and 0x8005, with
marker code in every flash page.

| Vector | User code ran | Executive in flash reached |
|---|---|---|
| `RETURN` | No | No |
| `RETFIE` | No | No |
| `MOVLP 7`, `CLRF PCL` | No | No |
| `MOVLP 7`, `CALLW` | No | No |
| `NOP`, `NOP` | Yes, but the counter did not advance | No |

Conclusions: debug entry does not push a return address, since `RETURN`
does not resume user code. Computed jumps do not leave the 0x8xxx space
either. Falling through eventually reaches user code and then restarts it,
which fits execution running off the end of the space and wrapping to
address 0.

At this point the owner of the board confirmed that the debug executive may
be outside the normal program address range.

### E7. Full map of the space

`e7.py`. Read 0x8000–0x8FFF.

Result: the content repeats exactly every 0x200. The space is 512 words.

| Range | Content |
|---|---|
| 0x8000–0x800F | IDs, vector, device ID, configuration, calibration |
| 0x8010–0x811F | Blank |
| 0x8120–0x8157 | Factory content |
| 0x8158–0x81BD | Blank |
| 0x81BE–0x81FF | Factory content, with gaps |

This also explained E1 to E3. `GOTO 0x700` executed at 0x8004 goes to
0x8700, which is the same cell as 0x8100: blank cells followed by the
factory content. Those early runs sent the core into that code. No effect on
the part was observed, but it was not intended.

It also explained how a one-word vector can work whatever the user's
`PCLATH` holds: every page of the space is the same 512 words.

## Phase 3: is the blank area usable

Asked before proceeding: may blank cells in the reserved space be
probe-written, given that a cell might turn out not to be erasable. The
answer was yes, carefully.

### E8. One cell at a time, bulk erase

`e8.py`. Write 0x3FFE (one bit cleared) to a single cell, bulk erase, read
the whole space and compare with the saved map.

| Cell | Write took | After bulk erase |
|---|---|---|
| 0x8010 | Yes | Restored |
| 0x8020 | Yes | **Still 0x3FFE** |

The script stopped there, as designed.

### E9. Row erase

`e9.py`. Address set to 0x8020, row erase command (0x11).

Result: 0x8020 read 0x3FFF again. Apart from the configuration words, which
the earlier bulk erase had cleared, the space matched the saved map.

### E10. Every blank row

`e10.py`. For each row with no factory content: write the first and last
cell, read, row erase, read.

| Rows | Write | Row erase |
|---|---|---|
| 0x8020 to 0x80E0 (seven rows) | Took | Restored |
| 0x8100, 0x8160, 0x8180 | Ignored | Nothing to restore |

Conclusion: 0x8010–0x80FF is writable and erasable, 240 words. 0x8100 and
above is write protected. The space again matched the saved map afterwards.

## Phase 4: an executive in the debug space

From here the vector was `GOTO 0x010` and the executive started at 0x8010.

### X1. Does it run, and what is the state on entry

`x1.py`. RAM channel. The executive logged a tag, the header-variant
registers, the stack registers, and the result of a `CALL`/`RETURN`.

| Item | Value |
|---|---|
| Tag | Logged. The executive ran straight out of reset |
| User marker | 0x00. User code had not started |
| "ICDCON0" (0xF8D) | 0x0C. Not plausible: bit 2 is not implemented in that register |
| "ICDSTAT" (0xF91) | 0x80 |
| "ICDIO" (0xF8C) | 0x0C. After writing 0x10 it read 0x00, and ICSPCLK did not go high |
| `STKPTR`, `TOS` | 0x1F, 0x0000. Unchanged inside a `CALL` |
| `CALL` and `RETURN` | Worked |
| `W`, `STATUS`, `BSR`, `PCLATH` | 0x00, 0x18, 0x00, 0x00 |

Conclusions: the executive location is right. The register definitions are
not.

### X2. Raw dump of the register area

`x2.py`. Logged 0xF8C–0xF9F and 0xFE0–0xFEF, then wrote four patterns to
0xF8C.

| Address | Value |
|---|---|
| 0xF8C, 0xF8D | 0x0C, 0x0C |
| 0xF8E | 0x80 |
| 0xF90, 0xF91 | 0x01, 0x80 |
| 0xF8F, 0xF92–0xF9F | 0x00 |
| 0xFE3 | 0x00 |

| Written to 0xF8C | Read back | Pins seen by the probe |
|---|---|---|
| 0xFF | 0x0C | |
| 0x00 | 0x00 | |
| 0x30 | 0x00 | |
| 0xF3 | 0xC0 | Both high |

So the pins can be driven, by some patterns only.

### X3. Which bits do what

`x3.py`. More patterns on 0xF8C, then each register in turn: read, write
0xFF, read, write 0x00, read. The suspected control register went last in
case writing it left debug mode.

| Register | Original | After 0xFF | After 0x00 | Reading |
|---|---|---|---|---|
| 0xF8C | | | | No pattern with bits 7:6 clear drove a pin. The output bits are 7 and 6, not 5 and 4 |
| 0xF8D | 0x0C | 0xCC | 0x00 | Same four bits, read back as written: a latch view |
| 0xF8E | 0x80 | 0xE0 | 0x80 | Bit 7 read only. Bits 6:5 writable |
| 0xF90 | 0x01 | 0xFF | 0x00 | Fully writable |
| 0xF91 | 0x80 | 0xFF | 0x00 | Fully writable |
| 0xF8F, 0xF92–0xF9F | 0x00 | 0x00 | 0x00 | Nothing there |

The 16-bit value 0x8001 in 0xF91:0xF90 was read as either a saved program
counter or a breakpoint. It later proved to be both.

## Phase 5: how to get back to user code

### X4. Candidate return instructions

`x4.py`. RAM channel. The executive counted its entries, logged
0xF90, 0xF91 and 0xF8E on each of the first sixteen, executed one candidate
opcode, and fell into a counting loop if the opcode did not leave.

| Opcode | Result |
|---|---|
| 0x0009 `RETFIE` | Three entries in 0.3 s, identical state, no user code. Consistent with a stack underflow reset and the 72 ms power-up timer each time |
| 0x0008 `RETURN` | No entries recorded. Not explained; not pursued |
| 0x0002, 0x0003 | Fell through |
| **0x0004** | **User code ran.** 227 entries. The log read 0x8013, 0x8014, 0x8013, … which are the two addresses of the test loop |
| 0x0005–0x0007, 0x000C–0x000F | Fell through |

Conclusion: opcode 0x0004 returns from debug mode. 0xF91:0xF90 holds the
user PC on entry. The core came back after every user instruction.

The later rows of that run showed a first entry at 0x0013 instead of 0x0001.
That was the first sign that some debug state survives a reset when power is
kept.

### X5. Why does it come back after each instruction

`x5.py`. Variants before the return: nothing, clear bit 7 of 0xF91, set
bits of 0xF8E, drive the pins.

The first run was unusable, because one variant cleared bit 7 and that state
carried into the variants after it. The run was repeated with a power cycle
before each variant.

| Variant | Entries | Result |
|---|---|---|
| Plain return | Continuous | One user instruction per entry |
| Clear bit 7 of 0xF91 | 1 | User code free-ran |
| Pins driven high or low before returning | Continuous | No difference. The pin drivers kept their state while user code ran |

Conclusion at the time: bit 7 of 0xF91 is a single-step flag, set at
power-on. This was later corrected (D6).

### X6. Halting a running target

`x6.py`. The executive cleared bit 7 on its first entry and returned. After
0.3 s the probe applied a stimulus.

| Stimulus | Entries | Second entry |
|---|---|---|
| None | 1 | |
| ICSPCLK high for 2 ms | 2 | PC 0x0013, bit 7 clear |
| ICSPDAT high for 2 ms | 1 | |
| Both high | 2 | PC 0x0013, bit 7 clear |
| MCLR pulse | 1 | The target reset and free-ran |

Conclusion: ICSPCLK high halts a running target.

### BSR

No dedicated experiment. In X5 the test executive changed `BSR` to 31 and
returned without restoring it, and user code went on writing to bank 2.
The marker byte landed in 0x120 and the counter in 0x121. So the hardware
saves and restores `BSR`. D1 later confirmed that 0xFE3 holds the saved
value: it read 2 after the user's `MOVLB 2`.

This is what makes a clean entry possible. `W` cannot be stored before a
bank is selected, and without the hardware save, selecting a bank would
destroy the user's `BSR`.

## Phase 6: the real executive

### D1. First session over the debug link

`d1.py`. The executive of `host/icd16f1.py`, with read, write and resume
commands.

The first attempt failed with a probe error, "VDD or VPP short circuit".
The target had halted and raised ICSPCLK, so the executive was alive. The
fault was a bug in the probe firmware. The debug link masks interrupts for
each byte. Afterwards the timer and ADC interrupts were both pending, and
the regulator loop treated a VPP sample as a VDD sample and counted a short
circuit. The interrupt routine was changed to act only on a conversion of
the right channel. A second bug introduced by that fix, in the voltage
readback, stalled the VPP regulator and was fixed in turn.

Then:

| Action | Result |
|---|---|
| After load | PC 0x0001, `W` 0x00, `STATUS` 0x18, `BSR` 0 |
| Step through `MOVLB 2`, `MOVLW 0x55`, `MOVWF`, `CLRF`, … | PC advanced by one each time. `BSR` became 2, `W` 0x55, Z set after `CLRF` |
| Resume, wait 0.2 s, halt | 16-bit counter in RAM advanced by 4,307 |
| Write RAM, read back | Correct |
| Read 16 bytes | 176 ms |

Two things in that run looked right and were not: the script "set the PC"
and only read the value back, and the "reset" at the end did not reset
anything. D3 and D8 found both.

### D2 and D3. Setting the PC does not work

`d2.py` scanned the unassigned opcodes for a software breakpoint by writing
the PC to each test block and resuming. Every case ended in the idle loop
with untouched counters. The PC write had not taken effect.

`d3.py` wrote 0x0230 with bit 7 set and stepped. The target did not come
back at all.

### D4. Is the register really the PC

`d4.py`. User code at 0x1234, to see values above 0xFF for the first time.

Result: 0xF91:0xF90 read 0x9234, 0x9235, … while stepping and 0x1235 or
0x1237 after a free run. So it does report the PC.

### D5. Byte order, flag, PCLATH

`d5.py`. Wrote a new address in both byte orders, with and without bit 7,
with and without matching `PCLATH`, then resumed. If the target did not
return, it was halted and inspected.

Result: in all nine cases the target ran freely and was found in its
original loop. The written address was never used as a resume address, and
with bit 7 set it did not step either.

### D6. It is a breakpoint

`d6.py`. Hypothesis: a write to 0xF91:0xF90 sets a hardware breakpoint, and
bit 15 enables it. A program of four counters incremented in sequence
showed exactly which instructions had run.

| Action | Halted with PC | Counters |
|---|---|---|
| Breakpoint at 0x22, run from reset | 0x0023 | 1, 1, 1, 0 |
| Resume without rewriting | 0x0024 | 1, 1, 1, 1 |
| Breakpoint at 0x20 | 0x0021 | 1, 0, 0, 0 |
| Breakpoint at 0x24, a `GOTO` | 0x0020 | 0, 1, 1, 1 |
| After a free run and halt: breakpoint := PC, six times | Next instruction each time | One counter per step |

Conclusions: the pair is a hardware breakpoint with an enable in bit 15. It
stops after the instruction at the address has executed. After a halt it
reads as the current PC, so leaving the enable set gives a single step.
That replaces the "step flag" reading from X5, and explains D3 and D5: the
target was running to a breakpoint it never reached. Power-on enables the
breakpoint at address 0, which is why a fresh target stops with PC = 1.

### D7. Software breakpoints

`d7.py`. The opcode scan again, steering with a dispatcher in user code
instead of a PC write. Each block increments a counter, executes the
candidate, and increments two more.

The first run was valid only for its first row, because `reset()` was
broken (D8). After the fix:

| Opcode | Result | Counters before, after, after |
|---|---|---|
| 0x0002 | Halted by itself, PC one past the opcode | 1, 0, 0 |
| 0x0003 | Halted by itself, PC one past the opcode | 1, 0, 0 |
| 0x0005–0x0007, 0x000C–0x000F, 0x0060, 0x0061 | Ran on | 1, 1, 1 |

Conclusion: 0x0002 and 0x0003 are software breakpoints. The others are
`NOP`s in user mode.

### D8. Reset

`d8.py`. A program whose first instruction has a visible side effect.

The original `reset()` pulsed MCLR while the target was halted. Afterwards
the PC read 0x0000 and the next step never returned. The MCLR pulse had done
nothing: the core ignores it in debug mode, and the "PC" was the value just
written to the breakpoint register.

The corrected sequence sets the breakpoint to address 0, resumes, and then
pulses MCLR.

| After | PC | Then |
|---|---|---|
| Power-on | 0x0001 | Steps normally |
| `reset()` | 0x0001 | Steps normally |
| `reset()` again | 0x0001 | |

User code runs for a few milliseconds between the resume and the reset.

## Phase 7: software breakpoints and moving the PC

The owner of the board supplied two recollections at this point. A software
breakpoint replaces an instruction in flash with a break instruction. And
software breakpoints are not thought to be restricted to particular
instructions. Whether the executive executes the replaced instruction was
not known.

D7 had already found the break instruction. The difficulty is what comes
next: the executive regains control with the PC one past the breakpoint, so
the original instruction has to be carried out some other way. Two
mechanisms were considered. Either the hardware executes an instruction
handed to it by the debugger, which is what the header variant's `ICDINST`
and `DBGINEX` names suggest, or the PC can be moved after all. An
unrestricted breakpoint needs one of them, because an executive that simply
runs the original instruction itself cannot do a `GOTO`, a `CALL` or a skip
on the user's behalf.

### D9. Scan of the data space, and the two control bits

`d9.py`, output in `d9.out`. The production register map (from the
toolchain's device database) was used to list every data address that is
neither a documented register nor RAM: 2,559 addresses.

| Part | Result |
|---|---|
| A. Read all 2,559 in debug mode | Non-zero only at 0xF8C, 0xF8D, 0xF8E, 0xF90, 0xF91: the registers already known |
| B. Write 0xFF and 0x00 to the 83 undocumented addresses of bank 31 not already known | None accepted a write |
| C. Bit 5 of 0xF8E set, breakpoint disabled, resume | **Came back by itself after one instruction**, PC 0x0001 to 0x0002. The bit stayed set |
| C. Bit 6 of 0xF8E set, breakpoint disabled, resume | Ran freely until halted. No difference seen |

Conclusion: bit 5 is a single step that does not need the breakpoint. No
instruction register in bank 31.

### D10. Write test of the other banks

`d10.py`, output in `d10.out`. D9 only read the addresses outside bank 31,
and a register that reads zero but accepts writes would have been missed.
All 2,470 were written with 0xFF and 0x00 and read back.

Result: none accepted a write. The executive was still responsive
afterwards.

Conclusion: the production part has no instruction-execute register in its
data space.

### D11. RETURN through the user's stack

`d11.py`, output in `d11.out`. The earlier `RETURN` tests (E6, X4) had an
empty stack. Here the host pushed a target address first: `STKPTR`
incremented, `TOSH:TOSL` written, both read back correctly. An experimental
fourth executive command then restored the registers and executed `RETURN`
instead of opcode 0x0004.

| Target | Result |
|---|---|
| 0x0230 | The executive came straight back. PC still 0x0001. `STKPTR` still incremented. The counters at the target were untouched |
| 0x1340 | The same |
| 0x0230 with the breakpoint armed on it | Contact lost; the target needed reloading |

Conclusion: `RETURN` in the debug space does not use the user's stack. It
restarts the executive. This matches X1, where a `CALL` in the executive did
not move `STKPTR`. The experimental command was removed again.

### Software breakpoints: where this leaves them

On this part, by experiment:

- the break instruction exists (0x0002, 0x0003);
- nothing in the data space executes a supplied instruction;
- the PC cannot be moved by writing the breakpoint register or through the
  stack.

So the mechanism that makes an unrestricted software breakpoint possible has
not been found, and may not be in the places examined. What could be built
from what is proven:

| Replaced instruction | Can be carried out by |
|---|---|
| Anything that does not change the PC | The host, by reading and writing registers and memory through the executive, or the executive running the instruction itself with the user's registers restored. The PC is already correct afterwards |
| `GOTO`, `CALL`, `RETURN`, `RETFIE`, `BRA`, `BRW`, `CALLW`, skips, writes to `PCL` | Nothing found |

That would be a restricted software breakpoint, with the hardware breakpoint
for the remaining cases. It also needs the executive to write flash during a
session, which means adding the self-write unlock sequence to it; reprogramming
over ICSP resets the target. None of this is implemented.

### A race in reset

Found while checking the OpenOCD port, not by an experiment here. The port
resumed the target and pulsed MCLR within a few hundred microseconds. The
executive had not yet finished restoring the registers and left debug mode,
where MCLR is ignored, so the pulse was lost and the port fell back to a
power cycle every time. The Python debugger had the same race and only
worked because it is slower. Both now wait 10 ms between the resume and the
pulse. With that, three resets in a row through OpenOCD stopped at the reset
vector with no power cycle.

## Phase 8: what a source-level debugger needs

The toolchain's LLDB needs two things the debugger did not have: the
hardware return stack, for backtraces, and program memory. Both scripts
use a small program with three nested calls (`test/calls/calls.hex` is the
same program as a HEX file).

### D12. Reading the return stack

`STKPTR` (0xFED) selects which entry `TOSH:TOSL` (0xFEF:0xFEE) shows. The
script halts inside the innermost function, writes each level 0–15 to
`STKPTR`, reads the entry, and puts `STKPTR` back.

```
halted at PC=0083
STKPTR=02  stack: 0021 0041 0061 0080 2200 0000 7FFF ...
read again: same, STKPTR=02
after release: PC=0082 STKPTR=02, returns to main counted: 1
```

Levels 0–2 are the three return addresses. The levels above `STKPTR` hold
whatever was left there. Reading is repeatable, and the program afterwards
returned through all three frames to `main`, so the walk disturbs nothing.
The executive's own `CALL`s do not show up, which agrees with D11: calls
made in debug mode do not use the user's stack.

### D13. Reading program memory

Earlier phases assumed program memory could not be read in a session. The
part can read its own flash: address in `EEADRH:EEADRL`, set `EEPGD` and
`RD` in `EECON1`, result in `EEDATH:EEDATL`. The core skips the two
instructions after the one that sets `RD`; the executive's write command
already ends in two `NOP`s for that reason. So three ordinary write
commands and two reads fetch a word.

- 23 words of program memory, programmed and blank, all matched the image.
- With `CFGS` also set the configuration space reads: 0x8004 `2810` (the
  debug vector), 0x8006 `2482` (device ID), 0x8007 `09C4`, 0x8008 `2EFF`
  (`DEBUG` enabled).
- 0x8010 and 0x8011, the first words of the executive, read `0000` this
  way although they are programmed. The executive area is not readable
  from inside.
- The five registers were restored and the target still stepped.

With `EEPGD` clear the same sequence reads the data EEPROM. The OpenOCD
target uses all three, and also identifies the device from 0x8006 so that
connecting a debugger does not need programming mode, which would reset
the target.

The same registers are how a program writes its own flash. That needs the
0x55, 0xAA unlock sequence in consecutive instructions, which cannot be
done with separate write commands; it would take a routine in the
executive. Not tried.

## Mistakes and corrections

| What | Where | How it was caught |
|---|---|---|
| Executive placed in user flash | E1–E3 | E6 and E7 |
| Early vector tests ran the core into the factory area | E1–E3 | E7, in hindsight |
| Reserved cells written before erase behaviour was known | E4 | Checked in E5; later writes were made one cell at a time after asking |
| Header-variant register addresses and bit positions assumed | E1, X1 | X2 and X3 |
| State carried between runs because power was kept | X4, first X5 | Power cycle before each variant |
| Bit 15 read as a single-step flag | X5 | D6 |
| "Set PC" believed to work | D1 | D2, D3, D5 |
| "Reset" believed to work | D1, D7 | D8 |
| Probe firmware raised a false power fault during debug traffic | D1 | Fixed in `firmware/power.c` |
| Reset pulsed MCLR before the executive had left debug mode | D8, OpenOCD port | The port fell back to a power cycle every time; a delay was added |
| Only two windows of the register space examined | X2, X3 | Whole data space scanned in D9 and D10 |
| Program memory assumed unreadable during a session | D1 onward | D13: the part's own flash read works from the executive |

## Open questions

- What bit 6 of 0xF8E does. The header name suggests it freezes
  peripherals while halted. That was not tested with a running peripheral.
- How Microchip's tools make software breakpoints work on any instruction,
  which the owner of the board believes they do. See "Software breakpoints".
- 0xF8D mirrors the pin latches. Whether it has another use is unknown.
- How many levels the debug-mode call stack has. The executive uses one.
- Whether the PC of a halted target can be changed by any means. Writing
  the breakpoint register does not (D5), and neither does a `RETURN` through
  the user's stack (D11).
- Why `RETURN` in X4 recorded no entries.
- Whether the executive's own program space offers something the data
  space does not. Only the behaviour of opcodes 0x0002–0x0007, 0x000C–0x000F,
  0x0060 and 0x0061 was tested there.
- How a sleeping target is halted. Seen with the OpenOCD target while
  running a program that ends in `SLEEP`; not examined with an experiment.
- Whether any of this holds on other revisions and other PIC16F1 parts.

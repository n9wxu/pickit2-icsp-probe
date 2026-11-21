# ICD experiment scripts

These are the scripts behind the development record in
[docs/icd.md](../../docs/icd.md), kept as they were run on 2026-11-18 to 2026-11-20. The
names match the experiment numbers there (`e0`–`e10`, `x1`–`x6`, `d1`–`d17`).

They are a record, not maintained code.

- `icdx.py` and `e3lib.py` are the shared helpers: the experimental
  executive, the EEPROM logger, and the `Lab` class that keeps the target
  powered so RAM survives reprogramming.
- `d9.py` reads the device database of the sibling toolchain project from
  `~/Documents/pic16f1_toolchain`.
- `d1.py` and `d7.py` use `Debugger` functions that were changed afterwards
  (a PC setter that never worked, and the earlier `reset()`).
- `d11.py` needs an executive command (`CMD_RETURN`) that was added for that
  experiment and removed again.
- `d9.out` to `d17.out` are the saved output of those runs.
- `d16.py` and `d17.py` test `host/emu16f1.py` and the software breakpoints of
  `Debugger` against the part; they should keep working.
- They assume a PIC16LF1937 powered by the probe at 3.3 V. Several of them
  write the debug space at 0x8004–0x80FF. None writes 0x8100 or above.

To leave a part clean after running any of them:

    host/pk2debug.py --vdd 3300 unload

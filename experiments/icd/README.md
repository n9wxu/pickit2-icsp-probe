# ICD experiment scripts

These are the scripts behind the development record in
[docs/icd.md](../../docs/icd.md), kept as they were run on 2026-11-18. The
names match the experiment numbers there (`e0`–`e10`, `x1`–`x6`, `d1`–`d11`).

They are a record, not maintained code.

- `icdx.py` and `e3lib.py` are the shared helpers: the experimental
  executive, the EEPROM logger, and the `Lab` class that keeps the target
  powered so RAM survives reprogramming.
- Paths to the project and the oscilloscope are hard-coded.
- `d1.py` and `d7.py` use `Debugger` functions that were changed afterwards
  (a PC setter that never worked, and the earlier `reset()`).
- `d11.py` needs an executive command (`CMD_RETURN`) that was added for that
  experiment and removed again.
- `d9.out`, `d10.out` and `d11.out` are the saved output of those runs.
- They assume a PIC16LF1937 powered by the probe at 3.3 V. Several of them
  write the debug space at 0x8004–0x80FF. None writes 0x8100 or above.

To leave a part clean after running any of them:

    host/pk2debug.py --vdd 3300 unload

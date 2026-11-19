import sys, time
sys.path.insert(0, sys.path[0] + "/../../host")
from pk2probe import *; from icd16f1 import *; from asm14 import *
CANDS = [0x0002, 0x0003, 0x0005, 0x0006, 0x0007, 0x000C, 0x000D, 0x000E, 0x000F, 0x0060, 0x0061]
a = Asm()
a.org(0); a.nop(); a.movlp(1); a.goto('disp'); a.org(4); a.retfie()
a.org(0x100); a.label('disp'); a.movf(0x70, W); a.brw()
for i in range(len(CANDS)): a.goto(f'b{i}')
for i, c in enumerate(CANDS):
    a.label(f'b{i}'); a.incf(0x71, F); a.word(c); a.incf(0x72, F); a.incf(0x73, F)
    here = a.pc; a.goto(here)
img = a.image(); img[0x8007] = 0x09C4; img[0x8008] = 0x3EFF
p = Probe(); d = Debugger(p, vdd_mv=3300); d.load(img)
for i, c in enumerate(CANDS):
    d.reset(); assert d.pc == 1, hex(d.pc)
    for r in (0x71, 0x72, 0x73): d.write8(r, 0)
    d.write8(0x70, i)
    d.resume(); time.sleep(0.05)
    self_halt = d.halted()
    if not self_halt: d.halt()
    at = a.labels[f'b{i}'] + 1
    print('opcode %04X at %04X: %s, PC=%04X, counters before/after/after = %s, F8E=%02X F8F=%02X' % (
        c, at, 'HALTED BY ITSELF' if self_halt else 'ran on', d.pc, [d.read8(0x71 + k) for k in range(3)], d.read8(0xF8E), d.read8(0xF8F)))
p.target_off(); p.close()

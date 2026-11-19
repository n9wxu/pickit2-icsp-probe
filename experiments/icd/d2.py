import sys, time
sys.path.insert(0, sys.path[0] + "/../../host")
from pk2probe import *; from icd16f1 import *; from asm14 import *
CANDS = [0x0002, 0x0003, 0x0005, 0x0006, 0x0007, 0x000C, 0x000D, 0x000E, 0x000F, 0x0060, 0x0061]
a = Asm()
a.org(0); a.nop(); a.movlp(0); a.goto('idle'); a.org(4); a.retfie()
a.org(0x10); a.label('idle'); a.bra('idle')
base = {}
for i, c in enumerate(CANDS):
    a.org(0x100 + 0x10 * i); base[c] = a.pc
    a.movlb(2); a.incf(0x20, F); a.word(c); a.incf(0x21, F); a.incf(0x22, F)
    here = a.pc; a.goto(here)                      # park
img = a.image(); img[0x8007] = 0x09C4; img[0x8008] = 0x3EFF
p = Probe(); d = Debugger(p, vdd_mv=3300); d.load(img)
for c in CANDS:
    for r in (0x120, 0x121, 0x122): d.write_data(r, 0)
    d.pc = base[c]
    d.resume(); time.sleep(0.05)
    self_halt = d.halted()
    if not self_halt: d.halt()
    r = d.registers()
    cnt = [d.read_data(0x120 + i) for i in range(3)]
    extra = [d.read8(x) for x in (0xF8E, 0xF8F, 0xF91)]
    print('opcode %04X at %04X: %s, PC=%04X (offset +%d), counters %s, F8E=%02X F8F=%02X F91=%02X' % (
        c, base[c] + 2, 'HALTED BY ITSELF' if self_halt else 'kept running', r['PC'], r['PC'] - base[c], cnt, *extra))
p.target_off(); p.close()

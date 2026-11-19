"""D11: can the executive move the user PC by pushing an address on the
user's stack and executing RETURN?  (Earlier RETURN tests had an empty
stack, which underflows and resets.)"""
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..', '..', 'host'))
from pk2probe import Probe                                              # noqa: E402
from icd16f1 import Debugger, build_executive, CMD_RETURN, EXEC_END, EXEC_START   # noqa: E402
from asm14 import Asm, F                                                # noqa: E402

STKPTR, TOSL, TOSH = 0xFED, 0xFEE, 0xFEF
a = Asm()
a.org(0); a.nop(); a.movlp(0); a.goto('m'); a.org(4); a.retfie()
a.org(0x20); a.label('m'); a.incf(0x70, F); a.incf(0x71, F); a.goto('m')
a.org(0x230); a.incf(0x74, F); a.incf(0x75, F); a.incf(0x76, F); here = a.pc; a.goto(here & 0x7FF)
a.org(0x1340); a.incf(0x78, F); a.incf(0x79, F); here = a.pc; a.goto(here & 0x7FF)
img = a.image(); img[0x8007] = 0x09C4; img[0x8008] = 0x3EFF
print('executive: %d words of %d' % (len(build_executive()) - 1, EXEC_END - EXEC_START))
p = Probe(); d = Debugger(p, vdd_mv=3300); d.load(img)

def counters(): return [d.read8(0x70 + i) for i in range(10)]
def jump(target):
    sp = (d.read8(STKPTR) + 1) & 0x1F
    d.write8(STKPTR, sp); d.write8(TOSL, target & 0xFF); d.write8(TOSH, target >> 8)
    print('   pushed %04X: STKPTR=%02X TOS=%02X%02X' % (target, d.read8(STKPTR), d.read8(TOSH), d.read8(TOSL)))
    d._xfer([CMD_RETURN])

for i in range(10): d.write8(0x70 + i, 0)
print('halted at PC=%04X, STKPTR=%02X' % (d.pc, d.read8(STKPTR)))
for target, bp_enabled in ((0x230, False), (0x1340, False), (0x230, True)):
    for i in range(10): d.write8(0x70 + i, 0)
    if bp_enabled: d.set_breakpoint(target)
    else: d.clear_breakpoint()
    print('RETURN to %04X with the breakpoint %s:' % (target, 'on that address' if bp_enabled else 'disabled'))
    jump(target)
    back = d._wait_halted(0.3)
    if not back:
        try: d.halt()
        except Exception as e: print('   could not halt: %s' % e); break
    print('   %s, PC=%04X, STKPTR=%02X, PCLATH=%02X, F8E=%02X, counters %s' % (
        'came back by itself' if back else 'ran until halted', d.pc, d.read8(STKPTR), d.read8(0x0A), d.read8(0xF8E), counters()))
p.target_off(); p.close()

import sys, time
sys.path.insert(0, sys.path[0] + "/../../host")
from pk2probe import *; from icd16f1 import *; from asm14 import *
a = Asm()
a.org(0); a.nop(); a.movlp(0); a.goto('idle'); a.org(4); a.retfie()
a.org(0x10); a.label('idle'); a.movlw(0x1D); a.bra('idle')
blocks = [0x100, 0x230, 0x340, 0x450]
for i, b in enumerate(blocks):
    a.org(b); a.movlw(0xA0 + i); a.nop(); a.nop(); here = a.pc; a.goto(here)
img = a.image(); img[0x8007] = 0x09C4; img[0x8008] = 0x3EFF
p = Probe(); d = Debugger(p, vdd_mv=3300); d.load(img)
def go_and_see(tag):
    d._xfer([CMD_GO])
    back = d._wait_halted(0.3)
    if not back: d.halt()
    r = d.registers()
    print('  %-44s -> %s at PC=%04X, W=%02X' % (tag, 'stepped ' if back else 'RAN FREE', r['PC'], r['W']))
for step in (True, False):
    for order in ('L,H', 'H,L'):
        for tgt in (blocks[1], blocks[2]):
            hi = (tgt >> 8) | (0x80 if step else 0)
            if order == 'L,H': d.write8(REG_PCL, tgt & 0xFF); d.write8(REG_PCH, hi)
            else:              d.write8(REG_PCH, hi); d.write8(REG_PCL, tgt & 0xFF)
            go_and_see('PC:=%04X order %s step flag %d' % (tgt, order, step))
# what if PCLATH is set as well?
d.write8(0x0A, 0x02); d.write8(REG_PCH, 0x82); d.write8(REG_PCL, 0x30); go_and_see('PC:=0230 with PCLATH=02, step')
p.target_off(); p.close()

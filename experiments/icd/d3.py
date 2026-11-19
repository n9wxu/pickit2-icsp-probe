import sys, time
sys.path.insert(0, sys.path[0] + "/../../host")
from pk2probe import *; from icd16f1 import *; from asm14 import *
a = Asm()
a.org(0); a.nop(); a.movlp(0); a.goto('idle'); a.org(4); a.retfie()
a.org(0x10); a.label('idle'); a.bra('idle')
for i in range(4):                      # four marker blocks: 0x100, 0x230, 0x340, 0x450
    a.org(0x100 + 0x110 * i + 0x20 * (i > 0)); a.movlw(0xA0 + i); here = a.pc; a.goto(here)
img = a.image(); img[0x8007] = 0x09C4; img[0x8008] = 0x3EFF
blocks = sorted(x for x in img if 0x100 <= x < 0x8000 and (img[x] & 0x3F00) == 0x3000)
print('marker blocks at', [hex(b) for b in blocks])
p = Probe(); d = Debugger(p, vdd_mv=3300); d.load(img)
def show(tag):
    r = d.registers(); print('  %-34s PC=%04X W=%02X  raw F90=%02X F91=%02X' % (tag, r['PC'], r['W'], d.read8(0xF90), d.read8(0xF91)))
show('after load')
for order in ('L then H', 'H then L'):
    for tgt in blocks[1:3]:
        if order == 'L then H':
            d.write8(REG_PCL, tgt & 0xFF); d.write8(REG_PCH, (tgt >> 8) | 0x80)
        else:
            d.write8(REG_PCH, (tgt >> 8) | 0x80); d.write8(REG_PCL, tgt & 0xFF)
        show('wrote %04X (%s), before step' % (tgt, order))
        d._xfer([CMD_GO]); d._wait_halted(1.0)
        show('after one step')
p.target_off(); p.close()

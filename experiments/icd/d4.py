import sys, time
sys.path.insert(0, sys.path[0] + "/../../host")
from pk2probe import *; from icd16f1 import *; from asm14 import *
a = Asm()
a.org(0); a.nop(); a.movlp(0x12); a.goto(0x1234 & 0x7FF); a.org(4); a.retfie()
a.org(0x1234); a.movlw(0x5A); a.label('l'); a.incf(0x70, F); a.nop(); a.goto(0x1235 & 0x7FF)
img = a.image(); img[0x8007] = 0x09C4; img[0x8008] = 0x3EFF
p = Probe(); d = Debugger(p, vdd_mv=3300); d.load(img)
def dump(tag):
    b = d.read_block(0xF8C, 0x14); e = d.read_block(0xFE0, 0x10)
    print('%-26s F8C: %s | FE0: %s | PCLATH=%02X' % (tag, b.hex(' '), e.hex(' '), d.read8(0x0A)))
dump('reset entry')
for i in range(5):
    d.step(); dump('step %d' % (i + 1))
d.resume(); time.sleep(0.05); d.halt(); dump('after run + halt')
d.resume(); time.sleep(0.05); d.halt(); dump('after run + halt')
p.target_off(); p.close()

import sys, time
sys.path.insert(0, sys.path[0] + "/../../host")
from pk2probe import *; from icd16f1 import *; from asm14 import *
a = Asm()
a.org(0); a.incf(0x70, F); a.incf(0x71, F); a.incf(0x72, F); a.label('l'); a.incf(0x73, F); a.goto('l')
img = a.image(); img[0x8007] = 0x09C4; img[0x8008] = 0x3EFF
p = Probe(); d = Debugger(p, vdd_mv=3300); d.load(img)
def st(tag): print('  %-28s PC=%04X raw=%02X%02X counters=%s' % (tag, d.pc, d.read8(REG_PCH), d.read8(REG_PCL), [d.read8(0x70 + i) for i in range(4)]))
st('after load (power-on)')
for i in range(4): d.write8(0x70 + i, 0)
d.step(); st('step'); d.step(); st('step')
d.resume(); time.sleep(0.05); d.halt(); st('run, halt')
for i in range(4): d.write8(0x70 + i, 0)
d.reset(); st('after reset()')
d.step(); st('step'); d.step(); st('step'); d.step(); st('step')
d.reset(); st('after reset() again')
p.target_off(); p.close()

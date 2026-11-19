import sys, time
sys.path.insert(0, sys.path[0] + "/../../host")
from pk2probe import *; from icd16f1 import *; from asm14 import *
ex = build_executive(); print('executive: %d words (room for %d)' % (len(ex) - 1, EXEC_END - EXEC_START))
a = Asm()
a.org(0); a.nop(); a.movlp(0); a.goto('u'); a.org(4); a.retfie(); a.org(0x10); a.label('u')
a.movlb(2); a.movlw(0x55); a.movwf(0x20); a.clrf(0x21); a.clrf(0x22)
a.label('ul'); a.incf(0x21, F); a.btfsc(STATUS, Z); a.incf(0x22, F); a.movlw(0xA7); a.bra('ul')
img = a.image(); img[0x8007] = 0x09C4; img[0x8008] = 0x3EFF
p = Probe(); d = Debugger(p, vdd_mv=3300)
t0 = time.time(); d.load(img); print('loaded in %.1f s; halted: %s' % (time.time() - t0, d.halted()))
print('after reset :', d.registers())
for i in range(8):
    d.step(); r = d.registers(); print('step %d      : PC=%04X W=%02X STATUS=%02X BSR=%02X' % (i + 1, r['PC'], r['W'], r['STATUS'], r['BSR']))
print('RAM 0x120..0x122:', [hex(d.read_data(0x120 + i)) for i in range(3)])
d.resume(); time.sleep(0.2); print('running; halted?', d.halted())
d.halt(); r = d.registers(); c1 = d.read_data(0x121) | (d.read_data(0x122) << 8)
print('halted at PC=%04X W=%02X BSR=%02X counter=%04X' % (r['PC'], r['W'], r['BSR'], c1))
d.resume(); time.sleep(0.2); d.halt(); c2 = d.read_data(0x121) | (d.read_data(0x122) << 8)
print('ran 0.2 s more: counter=%04X (advanced %d)' % (c2, (c2 - c1) & 0xFFFF))
d.write_data(0x121, 0x00); d.write_data(0x122, 0x80); d.pc = 0x15
print('after writes: counter=%04X PC=%04X' % (d.read_data(0x121) | (d.read_data(0x122) << 8), d.pc))
t0 = time.time(); blk = d.read_block(0x120, 16); print('block read 16 bytes in %.0f ms: %s' % ((time.time() - t0) * 1000, blk.hex(' ')))
d.reset(); print('after reset:', d.registers())
p.target_off(); p.close()

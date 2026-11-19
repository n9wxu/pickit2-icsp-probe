import sys, time
sys.path.insert(0, sys.path[0] + "/../../host")
from pk2probe import *; from icd16f1 import *; from asm14 import *
a = Asm()
a.org(0); a.nop(); a.movlp(0); a.goto('m'); a.org(4); a.retfie()
a.org(0x20); a.label('m')
a.incf(0x70, F)        # 0x20
a.incf(0x71, F)        # 0x21
a.incf(0x72, F)        # 0x22
a.incf(0x73, F)        # 0x23
a.goto('m')            # 0x24
a.org(0x1230)
a.incf(0x74, F); a.incf(0x75, F); a.movlp(0); a.goto('m')
img = a.image(); img[0x8007] = 0x09C4; img[0x8008] = 0x3EFF
p = Probe(); d = Debugger(p, vdd_mv=3300); d.load(img)
def bp(addr): d.write8(REG_PCL, addr & 0xFF); d.write8(REG_PCH, (addr >> 8) | 0x80)
def counters(): return [d.read8(0x70 + i) for i in range(4)]
def zero():
    for i in range(4): d.write8(0x70 + i, 0)
def run(tag, wait=0.2):
    d._xfer([CMD_GO]); back = d._wait_halted(wait)
    if not back: d.halt()
    print('  %-40s %s  PC=%04X raw=%02X%02X counters=%s' % (tag, 'BREAK   ' if back else 'no break', d.pc, d.read8(REG_PCH), d.read8(REG_PCL), counters()))
print('stopped at PC=%04X' % d.pc)
zero(); bp(0x22); run('breakpoint at 0x22, from reset')
run('go again without rewriting')
run('go again without rewriting')
zero(); bp(0x20); run('breakpoint at 0x20')
zero(); bp(0x24); run('breakpoint at 0x24 (the GOTO)')
# free run then halt, then step by putting the breakpoint on the current PC
d.write8(REG_PCH, d.read8(REG_PCH) & 0x7F); d._xfer([CMD_GO]); time.sleep(0.05); d.halt()
pc = d.pc; print('free run, halted at PC=%04X raw=%02X%02X' % (pc, d.read8(REG_PCH), d.read8(REG_PCL)))
for i in range(6):
    pc = d.pc; bp(pc); zero(); run('step from %04X (breakpoint := PC)' % pc)
p.target_off(); p.close()

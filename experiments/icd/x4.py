from icdx import *
import sys
def user(a):
    a.org(0); a.movlp(0); a.goto('u'); a.org(4); a.retfie(); a.org(0x10); a.label('u')
    a.movlb(2); a.movlw(0x55); a.movwf(0x20)
    a.label('ul'); a.incf(0x21, F); a.bra('ul')
lab = Lab()
cands = [int(x, 16) for x in sys.argv[1:]] or [0x0009, 0x0008]
for op in cands:
    def body(a):
        entry_logger(a, extra=(STATUS,))
        a.word(op)
        a.label('spin'); a.movlb(2); a.incf(0x22, F); a.goto('spin')
    ee, pins, _ = lab.ram_after(dbg_image(body, user))
    print('exit candidate %04X: exec spin count %02X (non-zero = fell through, did not leave)' % (op, ee[2]))
    show_entries(ee)
lab.off()

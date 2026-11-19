"""D12: read the whole hardware return stack of a halted target.

The stack is reached through STKPTR (0xFED) and TOSH:TOSL (0xFEF:0xFEE).
Point STKPTR at each level in turn, read the entry, put STKPTR back.  Then
let the program return through all its frames to show nothing was disturbed.
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..', '..', 'host'))
from pk2probe import Probe                       # noqa: E402
from icd16f1 import Debugger, DebugError         # noqa: E402
from asm14 import Asm, F                         # noqa: E402

STKPTR, TOSL, TOSH = 0xFED, 0xFEE, 0xFEF


def test_program():
    a = Asm()
    a.org(0); a.nop(); a.movlp(0); a.goto('m'); a.org(4); a.retfie()
    a.org(0x20); a.label('m')
    a.call('f1'); a.incf(0x72, F); a.goto('m')          # return address 0x21
    a.org(0x40); a.label('f1'); a.call('f2'); a.ret()   # 0x41
    a.org(0x60); a.label('f2'); a.call('f3'); a.ret()   # 0x61
    a.org(0x80); a.label('f3')
    a.label('w'); a.incf(0x71, F); a.movf(0x70, F); a.btfsc(0x03, 2); a.goto('w')
    a.clrf(0x70); a.ret()
    img = a.image()
    img[0x8007] = 0x09C4
    img[0x8008] = 0x3EFF
    return img


def read_stack(d):
    sp = d.read8(STKPTR)
    out = []
    for level in range(16):
        d.write8(STKPTR, level)
        out.append(d.read8(TOSL) | d.read8(TOSH) << 8)
    d.write8(STKPTR, sp)
    return sp, out


def main():
    p = Probe()
    d = Debugger(p, vdd_mv=3300)
    d.load(test_program())
    d.write8(0x70, 0); d.write8(0x72, 0)
    d.resume()
    d.halt()
    print('halted at PC=%04X' % d.pc)
    sp, stack = read_stack(d)
    print('STKPTR=%02X  stack: %s' % (sp, ' '.join('%04X' % v for v in stack)))
    sp2, stack2 = read_stack(d)
    print('read again: %s, STKPTR=%02X' % ('same' if (sp2, stack2) == (sp, stack) else 'DIFFERENT', sp2))
    d.write8(0x70, 1)            # let f3 return
    d.resume()
    import time; time.sleep(0.05)
    d.halt()
    print('after release: PC=%04X STKPTR=%02X, returns to main counted: %d' % (
        d.pc, d.read8(STKPTR), d.read8(0x72)))
    p.target_off()
    p.close()


if __name__ == '__main__':
    try:
        main()
    except DebugError as e:
        sys.exit('stopped: %s' % e)

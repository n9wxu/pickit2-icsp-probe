"""D14: can the PC of a halted target be moved with instructions in USER
flash?  D11 showed that a RETURN executed in the debug space does not use
the user's stack.  A RETURN executed in user mode must.

The gadget is two words, a break and a RETURN, at the same offset in every
page so that a CALL reaches it whatever PCLATH holds:

    G:    0x0002      break: the executive gets control with PC = G+1
    G+1:  RETURN      runs in user mode after the resume

A breakpoint site holds CALL G in place of its instruction.  At the halt
TOS is the site address + 1, which identifies the site.  The host then
edits the stack to give the effect of the replaced instruction and
resumes; the RETURN goes wherever TOS says.

    replaced instruction      stack edit
    anything without a jump   none (TOS is already site + 1)
    a skip that is taken      TOS = site + 2
    GOTO t                    TOS = t
    CALL t                    push t (site + 1 stays below it)
    RETURN                    pop (the caller's address is now on top)
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..', '..', 'host'))
from pk2probe import Probe                       # noqa: E402
from icd16f1 import Debugger, DebugError         # noqa: E402
from asm14 import Asm, F                         # noqa: E402

STKPTR, TOSL, TOSH, PCLATH = 0xFED, 0xFEE, 0xFEF, 0x00A
G = 0x7F0                                        # gadget offset in each page
NAMES = ['laps', 'S1+1', 'S1+2', 'S2+1', 'sub2', 'ret2', 't1', 'sub', 'page1']


def test_program():
    a = Asm()
    a.org(0); a.nop(); a.movlp(0); a.goto('m'); a.org(4); a.retfie()
    a.org(0x20); a.label('m')
    a.movlp(0)
    a.incf(0x70, F)
    a.label('S1'); a.call(G)            # site 1
    a.incf(0x71, F)
    a.incf(0x72, F)
    a.label('S2'); a.call(G)            # site 2: stands for CALL sub
    a.incf(0x73, F)
    a.call('sub2')
    a.incf(0x75, F)
    a.movlp(0x08); a.goto(0x900)
    a.org(0x60); a.label('t1'); a.incf(0x76, F); a.goto('S2')
    a.org(0x70); a.label('sub'); a.incf(0x77, F); a.ret()
    a.org(0x80); a.label('sub2'); a.incf(0x74, F)
    a.label('S3'); a.call(G)            # site 3: stands for RETURN
    a.org(0x900); a.incf(0x78, F)
    a.label('S4'); a.call(G)            # site 4, in page 1 with PCLATH = 8: stands for GOTO m
    for page in range(4):
        a.org(page * 0x800 + G); a.word(0x0002); a.ret()
    labels = dict(a.labels)
    img = a.image()
    img[0x8007] = 0x09C4
    img[0x8008] = 0x3EFF
    return img, labels


class Rig:
    def __init__(self, d):
        self.d = d

    def tos(self):
        return self.d.read8(TOSL) | self.d.read8(TOSH) << 8

    def set_tos(self, v):
        self.d.write8(TOSL, v & 0xFF); self.d.write8(TOSH, v >> 8)

    def push(self, v):
        self.d.write8(STKPTR, (self.d.read8(STKPTR) + 1) & 0x1F); self.set_tos(v)

    def pop(self):
        self.d.write8(STKPTR, (self.d.read8(STKPTR) - 1) & 0x1F)

    def counters(self):
        return [self.d.read8(0x70 + i) for i in range(len(NAMES))]

    def at_site(self, want_site, want_page):
        """Wait for the gadget's break and check where it came from."""
        d = self.d
        if not d.wait(0.5):
            d.halt()
            print('   NO HALT; stopped by hand at PC=%04X' % d.pc)
            return False
        pc, sp, tos = d.pc, d.read8(STKPTR), self.tos()
        ok = pc == want_page * 0x800 + G + 1 and tos == want_site + 1
        print('   halt PC=%04X STKPTR=%02X TOS=%04X PCLATH=%02X  %s' % (
            pc, sp, tos, d.read8(PCLATH), 'as expected' if ok else '<-- UNEXPECTED'))
        return ok

    def show(self, before):
        now = self.counters()
        diff = ', '.join('%s+%d' % (n, (b - a) & 0xFF) for n, a, b in zip(NAMES, before, now) if a != b)
        print('   ran: %s' % (diff or 'nothing'))
        return now


def main():
    p = Probe()
    d = Debugger(p, vdd_mv=3300)
    img, L = test_program()
    d.load(img)
    r = Rig(d)
    for i in range(len(NAMES)):
        d.write8(0x70 + i, 0)
    c = r.counters()
    print('start: PC=%04X STKPTR=%02X' % (d.pc, d.read8(STKPTR)))

    print('1. site 1, no stack edit (an instruction without a jump)')
    d.resume(); r.at_site(L['S1'], 0); c = r.show(c)
    d.resume()
    print('2. site 2, push sub (CALL sub)')
    r.at_site(L['S2'], 0); c = r.show(c)
    r.push(L['sub']); d.resume()
    print('3. site 3 inside sub2, pop (RETURN)')
    r.at_site(L['S3'], 0); c = r.show(c)
    r.pop(); d.resume()
    print('4. site 4 in page 1 with PCLATH=08, TOS = m (GOTO m)')
    r.at_site(L['S4'], 1); c = r.show(c)
    r.set_tos(L['m']); d.resume()
    print('5. site 1 again, reached with PCLATH from page 1?  TOS = site + 2 (a skip taken)')
    r.at_site(L['S1'], 0); c = r.show(c)
    r.set_tos(L['S1'] + 2); d.resume()
    print('6. site 2, plain; then on to site 3, pop; site 4, TOS = m')
    r.at_site(L['S2'], 0); c = r.show(c); d.resume()
    r.at_site(L['S3'], 0); c = r.show(c); r.pop(); d.resume()
    r.at_site(L['S4'], 1); c = r.show(c); r.set_tos(L['m']); d.resume()
    print('7. site 1, TOS = t1 (GOTO t1), then single step the RETURN instead of running')
    r.at_site(L['S1'], 0); c = r.show(c)
    r.set_tos(L['t1'])
    d.step()
    print('   after one step: PC=%04X (t1 is %04X) STKPTR=%02X' % (d.pc, L['t1'], d.read8(STKPTR)))
    c = r.show(c)
    d.step()
    print('   after another:  PC=%04X' % d.pc)
    c = r.show(c)
    d.resume()
    r.at_site(L['S2'], 0); c = r.show(c)
    print('final STKPTR=%02X' % d.read8(STKPTR))
    p.target_off()
    p.close()


if __name__ == '__main__':
    try:
        main()
    except DebugError as e:
        sys.exit('stopped: %s' % e)

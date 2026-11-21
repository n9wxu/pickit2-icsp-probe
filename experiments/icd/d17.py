"""D17: software breakpoints end to end, with the Debugger of host/icd16f1.py.

A small loop with a call, skips, a GOTO and a RETURN gets a breakpoint on
each kind of instruction.  The order of the stops and the program's own
counters show whether every replaced instruction was carried out as if it
had run.
"""
import os
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..', '..', 'host'))
from pk2probe import Probe                       # noqa: E402
from icd16f1 import Debugger, DebugError         # noqa: E402
from asm14 import Asm, F                         # noqa: E402

fails = []


def check(what, ok, detail=''):
    print('   %-58s %s %s' % (what, 'ok' if ok else 'FAILED', detail))
    if not ok:
        fails.append(what)


def program():
    a = Asm()
    L = {}

    def mark(name):
        L[name] = a.pc

    a.org(0); a.nop(); a.movlp(0); a.goto('main'); a.org(4); a.retfie()
    a.org(0x20); a.label('main')
    a.movlp(0)
    mark('incf'); a.incf(0x70, F)               # laps
    mark('call'); a.call('f1')
    mark('btfsc'); a.btfsc(0x70, 0)
    a.incf(0x71, F)                             # odd laps
    a.movlw(3); a.movwf(0x73)
    a.label('lp')
    mark('decfsz'); a.decfsz(0x73, F)
    mark('goto'); a.goto('lp')
    a.bra('over'); a.nop()
    a.label('over'); a.incf(0x72, F)            # laps
    mark('last'); a.goto('main')
    a.org(0x60); a.label('f1'); mark('f1'); a.incf(0x74, F)     # laps
    mark('return'); a.ret()
    img = a.image(); img[0x8007] = 0x09C4; img[0x8008] = 0x3EFF
    return img, L


def counters(d):
    return [d.read8(0x70 + i) for i in range(5)]


def consistent(c):
    """True for the counters as they are between laps."""
    laps = c[0]
    return c[1] == (laps + 1) // 2 and c[2] == laps and c[4] == laps


def main():
    img, L = program()
    name = {v: k for k, v in L.items()}
    state = os.path.join(tempfile.mkdtemp(), 'session.json')
    p = Probe()
    d = Debugger(p, vdd_mv=3300, state_path=state)
    d.load(img)
    print('gadget at offset %03X of each page' % d.gadget)
    for i in range(5):
        d.write8(0x70 + i, 0)

    def run():
        d.resume()
        if not d.wait(1.0):
            d.halt()
            return None
        return d.pc

    print('1. one breakpoint, on a plain instruction')
    t = time.time(); d.set_soft_breakpoint(L['incf']); dt = time.time() - t
    print('   set in %.1f s' % dt)
    pc = run()
    r = d.registers()
    check('stops with PC on the breakpoint', pc == L['incf'], 'PC=%04X' % (pc or 0))
    check('its instruction has not run', counters(d)[0] == 0)
    check('registers hide the gadget', r['PC'] == L['incf'] and r['STKPTR'] == 0x1F, 'STKPTR=%02X' % r['STKPTR'])
    d.step()
    check('a step runs just that instruction', d.pc == L['incf'] + 1 and counters(d)[0] == 1, 'PC=%04X' % d.pc)
    pc = run()
    check('a lap later it stops there again', pc == L['incf'] and counters(d) == [1, 1, 1, 0, 1], str(counters(d)))

    print('2. breakpoints on a CALL, a RETURN, two skips and two GOTOs as well')
    for n in ('call', 'return', 'btfsc', 'decfsz', 'goto', 'last'):
        d.set_soft_breakpoint(L[n])
    want = ['call', 'return', 'btfsc', 'decfsz', 'goto', 'decfsz', 'goto', 'decfsz', 'last', 'incf'] * 2
    got = []
    for _ in want:
        pc = run()
        got.append(name.get(pc, '%04X' % pc if pc is not None else 'no stop'))
    check('two laps stop in program order', got == want, '' if got == want else ' '.join(got))
    c = counters(d)
    check('the program counted as it would have alone', c[0] == 3 and consistent(c), str(c))

    print('3. stepping from breakpoints')
    d.step()
    pc = d.pc
    check('step from the first lands on the CALL breakpoint', pc == L['call'], 'PC=%04X' % pc)
    d.step()
    r = d.registers()
    check('step into the CALL', r['PC'] == L['f1'] and r['STKPTR'] == 0 and d._tos() == L['call'] + 1,
          'PC=%04X STKPTR=%02X' % (r['PC'], r['STKPTR']))
    d.step(); d.step()
    r = d.registers()
    check('two more steps return from it', r['PC'] == L['btfsc'] and r['STKPTR'] == 0x1F,
          'PC=%04X STKPTR=%02X' % (r['PC'], r['STKPTR']))

    print('4. a second debugger object picks the session up from the state file')
    pc = run()
    check('stopped at the next breakpoint', pc == L['btfsc'] or pc == L['decfsz'], name.get(pc, '?'))
    d2 = Debugger(p, vdd_mv=3300, state_path=state)
    check('it knows the breakpoints and the PC', sorted(d2.breaks) == sorted(d.breaks) and d2.pc == pc)
    d2.resume(); d2.wait(1.0)
    check('and can continue', name.get(d2.pc) in ('decfsz', 'goto'), name.get(d2.pc, '?'))
    d = d2

    print('5. remove them all while stopped at one, and run')
    stopped_at = d.pc
    for a in sorted(d.breaks):
        d.clear_soft_breakpoint(a)
    check('PC still reads as the breakpoint', d.pc == stopped_at, 'PC=%04X' % d.pc)
    rows = d.read_flash(0x20, 32) + d.read_flash(0x60, 32)
    orig = [img.get(a, 0x3FFF) for a in list(range(0x20, 0x40)) + list(range(0x60, 0x80))]
    check('flash is the original program again', rows == orig)
    before = counters(d)[0]
    d.resume(); time.sleep(0.1)
    check('the target runs without stopping', not d.halted())
    d.halt()
    d.resume(breakpoint=L['last']); d.wait(1.0)     # hardware breakpoint: on to the end of the lap
    c = counters(d)
    check('and counted correctly', c[0] > before + 5 and consistent(c), '%s PC=%04X' % (c, d.pc))
    check('nothing left on the stack', d.registers()['STKPTR'] in (0x1F, 0x00), 'STKPTR=%02X' % d.registers()['STKPTR'])

    print('6. things that must be refused')
    for what, addr in (('a breakpoint on the gadget', d.gadget), ('a breakpoint beyond the flash', 0x2000)):
        try:
            d.set_soft_breakpoint(addr)
            check(what, False, 'accepted')
        except DebugError as e:
            check(what, True)

    print('FAILED: %s' % ', '.join(fails) if fails else 'all passed')
    p.target_off()
    p.close()


if __name__ == '__main__':
    try:
        main()
    except DebugError as e:
        sys.exit('stopped: %s' % e)

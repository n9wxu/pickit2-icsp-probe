"""D9: look for the mechanism behind transparent software breakpoints.

A software breakpoint replaces an instruction in flash with a break opcode.
The executive regains control with the PC already past it and the PC cannot
be moved back, so the replaced instruction has to be executed some other
way.  The debug-header device file names an ICDINST register pair and a
DBGINEX bit for executing an instruction supplied by the debugger.  This
script looks for them on the production part.

  A  read every undocumented data address in debug mode; report non-zero ones
  B  write-test the undocumented addresses of bank 31 (and anything from A)
  C  see what bits 6 and 5 of the control register 0xF8E do on resume
"""
import json
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..', '..', 'host'))
from pk2probe import Probe                                    # noqa: E402
from icd16f1 import Debugger, DebugError, REG_PCH, REG_PCL, CMD_GO   # noqa: E402
from asm14 import Asm, F                                      # noqa: E402

DEVICE_DB = os.path.expanduser('~/Documents/pic16f1_toolchain/devices/pic16f1937.json')
KNOWN_DEBUG = {0xF8C, 0xF8D, 0xF8E, 0xF90, 0xF91, 0xFE3}


def documented():
    db = json.load(open(DEVICE_DB))
    used = {s['addr'] for s in db['sfrs']}
    for g in db['gpr']:
        used.update(range(g['begin'], g['end']))
    for bank in range(32):
        used.update(range(bank * 0x80, bank * 0x80 + 0x0C))          # core registers
        used.update(range(bank * 0x80 + 0x70, bank * 0x80 + 0x80))   # common RAM
    return used


def test_program():
    a = Asm()
    a.org(0); a.nop(); a.movlp(0); a.goto('m'); a.org(4); a.retfie()
    a.org(0x20); a.label('m')
    a.incf(0x70, F); a.incf(0x71, F); a.incf(0x72, F); a.incf(0x73, F); a.goto('m')
    img = a.image()
    img[0x8007] = 0x09C4
    img[0x8008] = 0x3EFF
    return img


def main():
    p = Probe()
    d = Debugger(p, vdd_mv=3300)
    d.load(test_program())
    known = documented()
    hidden = [a for a in range(0x1000) if a not in known]
    print('%d undocumented addresses' % len(hidden))

    print('A. non-zero undocumented addresses in debug mode:')
    nonzero = []
    for i in range(0, len(hidden), 16):
        chunk = hidden[i:i + 16]
        for a in chunk:
            v = d.read8(a)
            if v:
                nonzero.append(a)
                print('   %03X = %02X%s' % (a, v, '  (known debug register)' if a in KNOWN_DEBUG else ''))
    sys.stdout.flush()

    print('B. write test (original / after FF / after 00), bank 31 and anything from A:')
    targets = sorted(set(a for a in hidden if a >= 0xF80) | set(nonzero))
    for a in targets:
        if a in KNOWN_DEBUG:
            continue
        orig = d.read8(a)
        print('   %03X: %02X' % (a, orig), end='')
        sys.stdout.flush()
        d.write8(a, 0xFF); hi = d.read8(a)
        d.write8(a, 0x00); lo = d.read8(a)
        d.write8(a, orig)
        note = '  <-- writable' if (hi or lo != orig) else ''
        print(' / %02X / %02X%s' % (hi, lo, note))
        sys.stdout.flush()

    print('C. bits 6 and 5 of 0xF8E, breakpoint disabled, then resume:')
    for bit in (5, 6):
        for i in range(4):
            d.write8(0x70 + i, 0)
        pc0 = d.pc
        d.write8(REG_PCH, d.read8(REG_PCH) & 0x7F)
        d.write8(0xF8E, 1 << bit)
        print('   bit %d set: 0xF8E reads %02X' % (bit, d.read8(0xF8E)), end='')
        d._xfer([CMD_GO])
        back = d._wait_halted(0.3)
        if not back:
            d.halt()
        print(', resumed from %04X: %s, PC=%04X, counters %s, 0xF8E=%02X' % (
            pc0, 'CAME BACK BY ITSELF' if back else 'ran until halted', d.pc,
            [d.read8(0x70 + i) for i in range(4)], d.read8(0xF8E)))
        d.write8(0xF8E, 0)

    p.target_off()
    p.close()


if __name__ == '__main__':
    try:
        main()
    except DebugError as e:
        sys.exit('stopped: %s' % e)

"""D13: read program memory live from a halted target.

The part can read its own flash through EEADRH:EEADRL, EECON1 (EEPGD, RD)
and EEDATH:EEDATL.  The executive's write command leaves two NOPs after the
write for the two instructions the core skips after RD is set.  CFGS selects
the configuration space, so the same route should reach 0x8000 and up.
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..', '..', 'host'))
from pk2probe import Probe                       # noqa: E402
from icd16f1 import Debugger, DebugError         # noqa: E402
import d12                                       # noqa: E402

EEADRL, EEADRH, EEDATL, EEDATH, EECON1 = 0x191, 0x192, 0x193, 0x194, 0x195


def read_word(d, addr, cfgs=False):
    d.write8(EEADRL, addr & 0xFF)
    d.write8(EEADRH, (addr >> 8) & 0x7F)
    d.write8(EECON1, 0x81 | (0x40 if cfgs else 0))      # EEPGD | RD
    return d.read8(EEDATL) | d.read8(EEDATH) << 8


def main():
    p = Probe()
    d = Debugger(p, vdd_mv=3300)
    img = d12.test_program()
    d.load(img)
    saved = [d.read8(r) for r in (EEADRL, EEADRH, EEDATL, EEDATH, EECON1)]
    print('user registers before: %s' % ' '.join('%02X' % v for v in saved))
    bad = 0
    for a in list(range(0, 8)) + list(range(0x20, 0x24)) + list(range(0x40, 0x42)) + \
            list(range(0x80, 0x87)) + [0x100, 0x1FFF]:
        got, want = read_word(d, a), img.get(a, 0x3FFF)
        bad += got != want
        print('   %04X: read %04X, image %04X%s' % (a, got, want, '' if got == want else '  <-- differs'))
    print('program memory: %s' % ('all match' if not bad else '%d differ' % bad))
    print('configuration space (CFGS):')
    for a in (0x8000, 0x8004, 0x8006, 0x8007, 0x8008, 0x8010, 0x8011):
        print('   %04X: %04X' % (a, read_word(d, a & 0x7FFF, cfgs=True)))
    for r, v in zip((EEADRL, EEADRH, EEDATL, EEDATH), saved):
        d.write8(r, v)
    d.write8(EECON1, saved[4] & 0xF4)
    print('user registers after:  %s' % ' '.join(
        '%02X' % d.read8(r) for r in (EEADRL, EEADRH, EEDATL, EEDATH, EECON1)))
    d.step(); d.step()
    print('still steps: PC=%04X' % d.pc)
    p.target_off()
    p.close()


if __name__ == '__main__':
    try:
        main()
    except DebugError as e:
        sys.exit('stopped: %s' % e)

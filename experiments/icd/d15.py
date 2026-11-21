"""D15: can the executive write user flash during a debug session?

The part writes its own flash through EEADR, EEDAT and EECON1, started by
the 0x55, 0xAA unlock sequence, which must be consecutive instructions.
The executive has a command for that (CMD_UNLOCK); the host sets up the
registers with ordinary write commands.

A. Write 8 words (one set of write latches) into a blank row, read back.
B. Erase that row, read back.
C. Change one instruction of the running program (erase its row, rewrite
   all 32 words) and see the program behave differently.
D. Put the instruction back.
"""
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..', '..', 'host'))
from pk2probe import Probe                                   # noqa: E402
from icd16f1 import Debugger, DebugError, CMD_UNLOCK         # noqa: E402
from asm14 import Asm, F                                     # noqa: E402

EEADRL, EEADRH, EEDATL, EEDATH, EECON1 = 0x191, 0x192, 0x193, 0x194, 0x195
EEPGD, LWLO, FREE, WREN = 0x80, 0x20, 0x10, 0x04
ROW, LATCHES = 32, 8


def read_word(d, addr):
    d.write8(EEADRL, addr & 0xFF)
    d.write8(EEADRH, addr >> 8)
    d.write8(EECON1, EEPGD | 0x01)
    return d.read8(EEDATL) | d.read8(EEDATH) << 8


def read_row(d, addr):
    return [read_word(d, addr + i) for i in range(ROW)]


def erase_row(d, addr):
    d.write8(EEADRL, addr & 0xFF)
    d.write8(EEADRH, addr >> 8)
    d.write8(EECON1, EEPGD | FREE | WREN)
    d._xfer([CMD_UNLOCK])
    d.write8(EECON1, EEPGD)


def write_words(d, addr, words):
    """Write whole sets of latches starting at addr (a multiple of 8)."""
    for i, w in enumerate(words):
        a = addr + i
        last = (a % LATCHES) == LATCHES - 1 or i == len(words) - 1
        d.write8(EEADRL, a & 0xFF)
        d.write8(EEADRH, a >> 8)
        d.write8(EEDATL, w & 0xFF)
        d.write8(EEDATH, w >> 8)
        d.write8(EECON1, EEPGD | WREN | (0 if last else LWLO))
        d._xfer([CMD_UNLOCK])
    d.write8(EECON1, EEPGD)


def fmt(words):
    return ' '.join('%04X' % w for w in words)


def main():
    a = Asm()
    a.org(0); a.nop(); a.movlp(0); a.goto('m'); a.org(4); a.retfie()
    a.org(0x20); a.label('m'); a.incf(0x70, F); a.incf(0x71, F); a.goto('m')
    img = a.image(); img[0x8007] = 0x09C4; img[0x8008] = 0x3EFF
    p = Probe()
    d = Debugger(p, vdd_mv=3300)
    d.load(img)
    saved = [d.read8(r) for r in (EEADRL, EEADRH, EEDATL, EEDATH, EECON1)]

    print('A. write 8 words at 0x0400 (blank row)')
    pattern = [0x3000 | i * 0x11 for i in range(8)]
    print('   before: %s' % fmt(read_row(d, 0x400)[:10]))
    write_words(d, 0x400, pattern)
    got = read_row(d, 0x400)
    print('   after:  %s' % fmt(got[:10]))
    print('   %s; EECON1=%02X' % ('written' if got[:8] == pattern and got[8:] == [0x3FFF] * 24 else 'NOT as written',
                                 d.read8(EECON1)))

    print('B. erase the row')
    t = time.time(); erase_row(d, 0x400); dt = time.time() - t
    got = read_row(d, 0x400)
    print('   after:  %s' % fmt(got[:10]))
    print('   %s (%.0f ms)' % ('blank' if got == [0x3FFF] * 32 else 'NOT blank', dt * 1000))

    print('C. change INCF 0x71,F at 0x0021 to INCF 0x72,F in the running program')
    row = read_row(d, 0x20)
    print('   row 0x20: %s ...' % fmt(row[:4]))
    for i in range(3): d.write8(0x70 + i, 0)
    d.resume(); time.sleep(0.05); d.halt()
    print('   before: counters %s' % [d.read8(0x70 + i) for i in range(3)])
    new = list(row); new[1] = 0x0AF2
    t = time.time(); erase_row(d, 0x20); write_words(d, 0x20, new); dt = time.time() - t
    back = read_row(d, 0x20)
    print('   row 0x20: %s ...  %s (%.1f s)' % (fmt(back[:4]), 'as written' if back == new else 'NOT as written', dt))
    for i in range(3): d.write8(0x70 + i, 0)
    d.resume(); time.sleep(0.05); d.halt()
    print('   after:  counters %s, PC=%04X' % ([d.read8(0x70 + i) for i in range(3)], d.pc))

    print('D. put it back')
    erase_row(d, 0x20); write_words(d, 0x20, row)
    print('   row 0x20 %s' % ('restored' if read_row(d, 0x20) == row else 'NOT restored'))
    for i in range(3): d.write8(0x70 + i, 0)
    d.resume(); time.sleep(0.05); d.halt()
    print('   counters %s' % [d.read8(0x70 + i) for i in range(3)])

    for r, v in zip((EEADRL, EEADRH, EEDATL, EEDATH), saved):
        d.write8(r, v)
    d.write8(EECON1, saved[4] & 0xF4)
    d.step()
    print('still steps: PC=%04X' % d.pc)
    p.target_off()
    p.close()


if __name__ == '__main__':
    try:
        main()
    except DebugError as e:
        sys.exit('stopped: %s' % e)

"""D16: does the debugger's instruction emulation (host/emu16f1.py) match
the silicon?

For every instruction of a test program, with random register and memory
contents: note the state, let the emulation do the instruction, note the
result, put the state back, let the part execute the instruction, and
compare the two results and the two next addresses.

Usage: d16.py [laps]     (default 2; each lap uses new random values)
"""
import os
import random
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..', '..', 'host'))
from pk2probe import Probe                       # noqa: E402
from icd16f1 import Debugger, DebugError         # noqa: E402
from asm14 import Asm                            # noqa: E402
import emu16f1                                   # noqa: E402

STKPTR, TOSL, TOSH = 0xFED, 0xFEE, 0xFEF
# name: data address (as Debugger.read_data takes it)
WATCH = {'W': 0x09, 'STATUS': 0x03, 'BSR': 0x08, 'PCLATH': 0x0A, 'INTCON': 0x0B,
         'FSR0L': 0x04, 'FSR0H': 0x05, 'FSR1L': 0x06, 'FSR1H': 0x07,
         'STKPTR': STKPTR, 'TOSL': TOSL, 'TOSH': TOSH,
         'm20': 0x20, 'm21': 0x21, 'm22': 0x22, 'm23': 0x23, 'm70': 0x70, 'mA0': 0xA0,
         'OPTION': 0x95}
SHADOW = {'sSTATUS': 0xFE4, 'sW': 0xFE5, 'sBSR': 0xFE6, 'sPCLATH': 0xFE7,
          'sFSR0L': 0xFE8, 'sFSR0H': 0xFE9, 'sFSR1L': 0xFEA, 'sFSR1H': 0xFEB}
SUB_RET, SUB_RETLW, SUB_RETFIE = 0x100, 0x102, 0x104


def fd(hi, f, d):
    return hi << 8 | d << 7 | f


def build():
    a = Asm()
    tests = {}

    def T(name, word, pad=0, **pre):
        tests[a.pc] = (name, word, pre)
        a.word(word)
        for _ in range(pad):
            a.nop()

    a.org(0); a.nop(); a.movlp(0); a.goto(0x20); a.org(4); a.retfie()
    a.org(0x20)
    ops = (('SUBWF', 0x02), ('DECF', 0x03), ('IORWF', 0x04), ('ANDWF', 0x05), ('XORWF', 0x06),
           ('ADDWF', 0x07), ('MOVF', 0x08), ('COMF', 0x09), ('INCF', 0x0A), ('RRF', 0x0C),
           ('RLF', 0x0D), ('SWAPF', 0x0E), ('LSLF', 0x35), ('LSRF', 0x36), ('ASRF', 0x37),
           ('SUBWFB', 0x3B), ('ADDWFC', 0x3D))
    for name, hi in ops:
        T(name + ' 0x20,F', fd(hi, 0x20, 1))
        T(name + ' 0x20,W', fd(hi, 0x20, 0))
    T('SUBWF equal', fd(0x02, 0x20, 0), W=0x37, m20=0x37)
    T('ADDWF carry', fd(0x07, 0x20, 1), W=0xFF, m20=0x01)
    T('INCF to zero', fd(0x0A, 0x20, 1), m20=0xFF)
    T('CLRF 0x20', 0x01A0)
    T('CLRW', 0x0100)
    T('MOVWF 0x20', 0x00A0)
    T('MOVWF 0x70', 0x00F0)
    T('DECFSZ 0x20,F', fd(0x0B, 0x20, 1), pad=1)
    T('DECFSZ skips', fd(0x0B, 0x20, 1), pad=1, m20=1)
    T('INCFSZ 0x20,W', fd(0x0F, 0x20, 0), pad=1)
    T('INCFSZ skips', fd(0x0F, 0x20, 1), pad=1, m20=0xFF)
    T('BCF 0x20,3', 0x1000 | 3 << 7 | 0x20)
    T('BSF 0x20,6', 0x1400 | 6 << 7 | 0x20)
    T('BTFSC 0x20,5', 0x1800 | 5 << 7 | 0x20, pad=1)
    T('BTFSS 0x20,5', 0x1C00 | 5 << 7 | 0x20, pad=1)
    T('BTFSC 0x20,0', 0x1800 | 0 << 7 | 0x20, pad=1)
    T('BTFSS 0x20,7', 0x1C00 | 7 << 7 | 0x20, pad=1)
    for name, hi in (('ADDLW', 0x3E), ('ANDLW', 0x39), ('IORLW', 0x38), ('MOVLW', 0x30),
                     ('SUBLW', 0x3C), ('XORLW', 0x3A)):
        T(name + ' 0x5C', hi << 8 | 0x5C)
    T('MOVLB 1', 0x0021)
    T('INCF 0x20,F in bank 1', fd(0x0A, 0x20, 1), BSR=1)
    T('MOVLP 0x15', 0x3180 | 0x15)
    T('ADDWF INDF0,F', fd(0x07, 0x00, 1))
    T('MOVF INDF1,W (linear)', fd(0x08, 0x01, 0))
    T('MOVF INDF0,W (flash)', fd(0x08, 0x00, 0), FSR0L=0x21, FSR0H=0x80)
    T('MOVIW ++FSR0', 0x0010)
    T('MOVIW --FSR0', 0x0011)
    T('MOVIW FSR1++', 0x0016)
    T('MOVIW FSR1--', 0x0017)
    T('MOVWI ++FSR1', 0x001C)
    T('MOVWI --FSR1', 0x001D)
    T('MOVWI FSR0++', 0x001A)
    T('MOVWI FSR0--', 0x001B)
    T('MOVIW 2[FSR0]', 0x3F00 | 2)
    T('MOVIW -1[FSR1]', 0x3F40 | 0x3F)
    T('MOVWI 1[FSR0]', 0x3F80 | 1)
    T('MOVWI -2[FSR1]', 0x3FC0 | 0x3E)
    T('ADDFSR FSR0,5', 0x3100 | 5)
    T('ADDFSR FSR1,-3', 0x3140 | 0x3D)
    T('ADDWF STATUS,F', fd(0x07, 0x03, 1))
    T('MOVWF STATUS', 0x0083)
    T('CLRF STATUS', 0x0183)
    T('BSF STATUS,0', 0x1400 | 0 << 7 | 0x03)
    T('RLF STATUS,F', fd(0x0D, 0x03, 1))
    T('INCF STATUS,F', fd(0x0A, 0x03, 1))
    T('SWAPF STATUS,F', fd(0x0E, 0x03, 1))
    T('ADDWF INDF0,F (STATUS)', fd(0x07, 0x00, 1), FSR0L=0x03, FSR0H=0x00)
    T('INCF WREG,F', fd(0x0A, 0x09, 1))
    T('ADDWF WREG,W', fd(0x07, 0x09, 0))
    T('INCF FSR0L,F', fd(0x0A, 0x04, 1))
    T('MOVF BSR,W', fd(0x08, 0x08, 0))
    T('MOVF PCL,W', fd(0x08, 0x02, 0))
    T('ADDWF PCL,F', fd(0x07, 0x02, 1), pad=2, W=random.choice((0, 1, 2)))
    T('BRW', 0x000B, pad=2, W=random.choice((0, 1, 2)))
    T('NOP', 0x0000)
    T('OPTION', 0x0062)
    T('GOTO', 0x2800 | (a.pc + 2), pad=1)
    T('BRA +1', 0x3200 | 1, pad=1)
    a.goto(0x182); back = a.pc              # out to the backward branch below and back
    T('CALL', 0x2000 | SUB_RET)
    T('CALL (RETLW)', 0x2000 | SUB_RETLW)
    T('CALLW', 0x000A, W=SUB_RET & 0xFF, PCLATH=SUB_RET >> 8)
    T('CALL (RETFIE)', 0x2000 | SUB_RETFIE)
    a.goto(0x20)
    end = a.pc
    a.org(SUB_RET); T('RETURN', 0x0008)
    a.org(SUB_RETLW); T('RETLW 0xA5', 0x34A5)
    a.org(SUB_RETFIE); T('RETFIE', 0x0009)
    a.org(0x181); a.goto(back)
    T('BRA -2', 0x3200 | (-2 & 0x1FF))      # at 0x182, to 0x181
    img = a.image()
    img[0x8007] = 0x09C4
    img[0x8008] = 0x3EFF
    return img, tests, end


def main():
    laps = int(sys.argv[1]) if len(sys.argv) > 1 else 2
    seed = random.randrange(1 << 30)
    random.seed(seed)
    print('seed %d' % seed)
    img, tests, end = build()
    p = Probe()
    d = Debugger(p, vdd_mv=3300)
    d.load(img, gadget=False)

    def snap():
        return {n: d.read_data(a) for n, a in WATCH.items()}

    def put(state):
        for n, v in state.items():
            d.write_data({**WATCH, **SHADOW}[n], v)

    fails = done = 0
    for lap in range(laps):
        seen = set()
        while True:
            pc = d._real_pc()
            if pc not in tests:
                if pc == end - 1 and seen:
                    d._raw_step()               # the GOTO back to the start
                    break
                d._raw_step()                   # padding, vectors, glue
                continue
            name, word, pre = tests[pc]
            seen.add(pc)
            r = random.randrange
            state = {'W': r(256), 'STATUS': 0x18 | r(8), 'BSR': 0, 'PCLATH': (pc + 1) >> 8, 'INTCON': 0,
                     'FSR0L': 0x21, 'FSR0H': 0x00, 'FSR1L': 0x22, 'FSR1H': 0x20,
                     'm20': r(256), 'm21': r(256), 'm22': r(256), 'm23': r(256), 'm70': r(256), 'mA0': r(256)}
            if word == 0x0009:
                state.update({n: r(256) for n in SHADOW})
                state['sBSR'] &= 0x1F; state['sPCLATH'] = (pc + 1) >> 8; state['sSTATUS'] &= 0x07
            state.update(pre)
            put(state)
            before = snap()
            nxt = emu16f1.execute(d, word, pc)
            emu = snap()
            put({n: v for n, v in before.items() if n not in ('TOSL', 'TOSH')})
            d._raw_step()
            real = snap()
            real_pc = d._real_pc()
            done += 1
            diff = ['%s emu %02X part %02X' % (n, emu[n], real[n]) for n in WATCH if emu[n] != real[n]]
            if nxt != real_pc:
                diff.append('next emu %04X part %04X' % (nxt, real_pc))
            if diff:
                fails += 1
                print('%04X %-24s DIFFERS: %s   (W=%02X STATUS=%02X m20=%02X)' % (
                    pc, name, '; '.join(diff), before['W'], before['STATUS'], before['m20']))
            elif lap == 0:
                print('%04X %-24s same, next %04X' % (pc, name, nxt))
            d.write_data(0x0B, 0)               # RETFIE leaves GIE set
        print('lap %d: %d instructions' % (lap + 1, len(seen)))
        if len(seen) != len(tests):
            print('NOT REACHED: %s' % ', '.join(tests[a][0] for a in tests if a not in seen))
    print('%d comparisons, %d differ' % (done, fails))
    p.target_off()
    p.close()


if __name__ == '__main__':
    try:
        main()
    except DebugError as e:
        sys.exit('stopped: %s' % e)

from icdx import *
import sys
DRET = 0x0004
def variant(pre):
    def body(a):
        entry_logger(a, extra=(R_PIN,))
        pre(a)
        a.word(DRET)
        a.label('spin'); a.movlb(2); a.incf(0x22, F); a.goto('spin')
    return dbg_image(body)
tests = {
 'A plain return':                 lambda a: None,
 'B clear bit7 of F91':            lambda a: a.bcf(R_PCH, 7),
 'C set F8E bit5 (SSTEP)':         lambda a: a.bsf(R_CON, 5),
 'D set F8E bit6 (FREEZ)':         lambda a: a.bsf(R_CON, 6),
 'E drive CLK high, DAT high':     lambda a: (a.movlw(0xC0), a.movwf(R_PIN)),
 'F drive CLK high, DAT low':      lambda a: (a.movlw(0x40), a.movwf(R_PIN)),
 'G drive CLK low, DAT high':      lambda a: (a.movlw(0x80), a.movwf(R_PIN)),
}
lab = Lab()
sel = sys.argv[1:] or list('ABCDEFG')
for name, pre in tests.items():
    if name[0] not in sel: continue
    lab.first = True          # power cycle: start from the power-on state
    ee, pins, _ = lab.ram_after(variant(pre))
    print('%-28s pins %02x  user marker %02X count %02X  entries %3d  first: %s' % (name, pins, ee[0], ee[1], ee[3],
          ' | '.join(hexs(ee[0x10 + 4*i: 0x14 + 4*i]) for i in range(min(5, ee[3])))))
lab.off()

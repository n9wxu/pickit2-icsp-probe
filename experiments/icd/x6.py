from icdx import *
import sys
DRET = 0x0004
def body(a):
    entry_logger(a, extra=(R_PIN,))
    a.movf(INDF0, W); a.xorlw(1); a.btfss(STATUS, Z); a.goto('spin')
    a.bcf(R_PCH, 7); a.word(DRET)                       # first entry: let the target run
    a.label('spin'); a.movlb(2); a.incf(0x22, F); a.goto('spin')
def drive(v, ms=2):
    def f(lab):
        p = lab.p; p.pins(v); p.delay_ms(ms); p.pins(PINS_LOW); p.delay_ms(1); p.pins(PINS_IDLE); p.flush()
    return f
def mclr(lab):
    p = lab.p; p.mclr(MCLR_GROUND); p.delay_ms(5); p.mclr(MCLR_RELEASE); p.flush(); time.sleep(0.2)
stims = {'none (control)': None, 'CLK high pulse': drive(PIN_CLK | PIN_DAT_IN), 'DAT high pulse': drive(PIN_DAT | PIN_CLK_IN),
         'CLK and DAT high pulse': drive(PIN_CLK | PIN_DAT), 'MCLR reset pulse': mclr}
lab = Lab(); img = dbg_image(body)
for name, st in stims.items():
    lab.first = True
    ee, pins, pins2 = lab.ram_after(img, stimulus=st)
    print('%-24s entries %d  exec spin %02X  user count %02X  log: %s' % (name, ee[3], ee[2], ee[1],
          ' | '.join(hexs(ee[0x10 + 4*i: 0x14 + 4*i]) for i in range(min(4, ee[3])))))
lab.off()

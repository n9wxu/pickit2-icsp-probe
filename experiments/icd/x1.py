from icdx import *
def user(a):
    a.org(0); a.movlp(0); a.goto('u'); a.org(4); a.retfie(); a.org(0x10); a.label('u')
    a.movlb(2); a.movlw(0x55); a.movwf(0x20)
    a.label('ul'); a.incf(0x21, F); a.bra('ul')
def dbgexec(a):
    a.org(0x8010)
    a.movwf(SW); a.movf(STATUS, W); a.movwf(SSTATUS); a.movf(BSR, W); a.movwf(SBSR); a.movf(PCLATH, W); a.movwf(SPCLATH)
    a.movlw(0x30); a.movwf(FSR1L); a.movlw(0x01); a.movwf(FSR1H)
    a.movlw(0xE5); a.movwi_postinc(1)
    a.movlb(31)
    for r in (ICDCON0, ICDSTAT, ICDIO, BSRICDSHAD, STKPTR, TOSL, TOSH):
        a.movf(r, W); a.movwi_postinc(1)
    for r in (SW, SSTATUS, SBSR, SPCLATH):
        a.movf(r, W); a.movwi_postinc(1)
    a.movlw(0x10); a.movwf(ICDIO); a.movf(ICDIO, W); a.movwi_postinc(1)     # CLK out high
    a.call('sub')                                                         # does CALL/RETURN work here?
    a.movlw(0xC2); a.movwi_postinc(1)
    a.movf(STKPTR, W); a.movwi_postinc(1)
    a.label('spin'); a.movlb(2); a.incf(0x22, F); a.goto('spin')
    a.label('sub'); a.movlw(0xC1); a.movwi_postinc(1)
    a.movlb(31); a.movf(TOSL, W); a.movwi_postinc(1); a.movf(TOSH, W); a.movwi_postinc(1)
    a.ret()
a = Asm(); user(a); dbgexec(a); w = a.image()
print('executive size: %d words' % sum(1 for x in w if x >= 0x8010))
w[0x8004] = 0x2810; w[0x8007] = 0x09C4; w[0x8008] = 0x2EFF
lab = Lab()
ee, pins, _ = lab.ram_after(w)
names = 'tag ICDCON0 ICDSTAT ICDIO BSRSHAD STKPTR TOSL TOSH W STATUS BSR PCLATH ICDIO:clk C1 sub.TOSL sub.TOSH C2 STKPTR'.split()
print('pins while in debug: %02x (bit2 = CLK)' % pins)
print('user [120..122] =', ' '.join('%02X' % b for b in ee[0:3]), ' (55 = user ran, user count, exec spin count)')
print('exec log:', ' '.join('%s=%02X' % kv for kv in zip(names, ee[0x10:0x10 + len(names)])))
lab.off()

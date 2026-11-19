from icdx import *
def set_log_ptr(a):
    a.movlw(0x30); a.movwf(FSR1L); a.movlw(0x01); a.movwf(FSR1H)      # exec log at 0x130
def user(a):
    a.org(0); a.movlp(0); a.goto('u'); a.org(4); a.retfie(); a.org(0x10); a.label('u')
    a.movlb(2); a.movlw(0x55); a.movwf(0x20)        # 0x120 = 0x55: user code ran
    a.label('ul'); a.incf(0x21, F); a.bra('ul')     # 0x121 counts
def exec_ram(a, base, tag):
    L = lambda n: f'{n}_{tag}'
    a.org(base)
    a.movwf(SW); a.movf(STATUS, W); a.movwf(SSTATUS); a.movf(BSR, W); a.movwf(SBSR); a.movf(PCLATH, W); a.movwf(SPCLATH)
    set_log_ptr(a)
    a.movlw(0xE0 + tag); a.movwi_postinc(1)
    a.movlb(31)
    for r in (ICDCON0, ICDSTAT, ICDIO, BSRICDSHAD, STKPTR, TOSL, TOSH):
        a.movf(r, W); a.movwi_postinc(1)
    for r in (SW, SSTATUS, SBSR, SPCLATH):
        a.movf(r, W); a.movwi_postinc(1)
    a.movlw(0x10); a.movwf(ICDIO); a.movf(ICDIO, W); a.movwi_postinc(1)   # CLK out high, read back
    a.movlw(0x20); a.movwf(ICDIO); a.movf(ICDIO, W); a.movwi_postinc(1)   # DAT out high
    a.movlw(0xEE); a.movwi_postinc(1)
    a.label(L('spin')); a.movlb(2); a.incf(0x22, F); a.bra(L('spin'))      # 0x122 counts in exec
def image(cfg2=0x2EFF, vec=0x2F00, vec2=None):
    a = Asm(); user(a)
    for pg in range(4): exec_ram(a, 0x700 + 0x800 * pg, pg)
    w = a.image(); w[0x8004] = vec
    if vec2 is not None: w[0x8005] = vec2
    w[0x8007] = 0x09C4; w[0x8008] = cfg2; return w

names = 'tag ICDCON0 ICDSTAT ICDIO BSRSHAD STKPTR TOSL TOSH W STATUS BSR PCLATH ICDIO:clk ICDIO:dat EE'.split()

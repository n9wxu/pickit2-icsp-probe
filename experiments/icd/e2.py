from icdx import *
def user(a):
    a.org(0)
    a.movlp(0); a.goto('ustart')
    a.org(4); a.retfie()
    a.org(0x10)
    a.label('ustart')
    a.clrf(EEA)
    a.movlw(0x55); a.call('ulog')            # EE[0] = 0x55: user code ran
    a.movlb(31)
    a.movf(ICDCON0, W); a.call('ulog')       # EE[1]
    a.movf(ICDSTAT, W); a.call('ulog')       # EE[2]
    a.movf(ICDIO, W); a.call('ulog')         # EE[3]
    a.movlw(0x10); a.movwf(ICDIO)            # try: CLK output high from user mode
    a.movf(ICDIO, W); a.call('ulog')         # EE[4]
    a.movlb(1); a.movf(0x0D, W); a.call('ulog')   # TRISB  EE[5]
    a.movlb(1); a.bcf(0x0D, 7); a.movlb(2); a.bsf(0x0D, 7)   # try RB7 (PGD) = 1 as plain port
    a.movlb(0); a.movf(0x0D, W); a.call('ulog')   # PORTB EE[6]
    a.movlw(0xEE); a.call('ulog')            # EE[7] end marker
    a.movlb(0); a.clrf(0x20)
    a.label('uloop'); a.incf(0x20, F); a.bra('uloop')
    ee_log_sub(a, 'ulog')

def exec_logger(a, base, tag):
    """Executive that only logs its entry to EEPROM[0x10 * (tag + 1)...]"""
    L = lambda n: f'{n}_{tag}'
    a.org(base)
    a.movwf(SW); a.movf(STATUS, W); a.movwf(SSTATUS); a.movf(BSR, W); a.movwf(SBSR); a.movf(PCLATH, W); a.movwf(SPCLATH)
    a.movlp(base >> 8)
    a.movlw(0x10 * (tag + 1)); a.movwf(EEA)
    a.movlw(0xE0 + tag); a.call(L('elog'))
    for r in (ICDCON0, ICDSTAT, ICDIO, BSRICDSHAD, STKPTR, TOSL, TOSH):
        a.movlb(31); a.movf(r, W); a.call(L('elog'))
    for r in (SW, SSTATUS, SBSR, SPCLATH):
        a.movf(r, W); a.call(L('elog'))
    a.movlb(31); a.movlw(0x10); a.movwf(ICDIO)     # CLK output high
    a.label(L('spin')); a.bra(L('spin'))
    ee_log_sub(a, L('elog'))

def build2(config2):
    a = Asm(); user(a)
    for page in range(4): exec_logger(a, 0x700 + 0x800 * page, page)
    w = a.image(); w[0x8004] = 0x2F00; w[0x8007] = 0x09C4; w[0x8008] = config2
    return w

for name, cfg2 in (('DEBUG off', 0x3EFF), ('DEBUG on', 0x2EFF)):
    s = Session(); s.load(build2(cfg2), quiet=True); s.start()
    time.sleep(0.5)
    pins = s.pins()
    ee = read_eeprom(s, 0x50)
    print(name, ' pins %02x' % pins)
    print('  user  EE[00..07]:', ' '.join('%02X' % b for b in ee[0:8]), '  (55, ICDCON0, ICDSTAT, ICDIO, ICDIO after write, TRISB, PORTB, EE)')
    for pg in range(4):
        row = ee[0x10*(pg+1):0x10*(pg+1)+12]
        if any(b != 0xFF for b in row): print('  exec page %d log:' % pg, ' '.join('%02X' % b for b in row), ' (tag, ICDCON0, ICDSTAT, ICDIO, BSRSHAD, STKPTR, TOSL, TOSH, W, STATUS, BSR, PCLATH)')
    s.off(); s.p.close()

"""Experimental debug executive and harness (exploration, not the final code)."""
import sys, time
sys.path.insert(0, sys.path[0] + "/../../host")
from pk2probe import *
from asm14 import *

# bank 31 offsets
ICDIO, ICDCON0, ICDSTAT, ICDINSTL, ICDINSTH = 0x0C, 0x0D, 0x11, 0x16, 0x17
ICDBK0CON, ICDBK0L, ICDBK0H, BSRICDSHAD = 0x1C, 0x1D, 0x1E, 0x63
STATUS_SHAD, WREG_SHAD, BSR_SHAD, PCLATH_SHAD = 0x64, 0x65, 0x66, 0x67
STKPTR, TOSL, TOSH = 0x6D, 0x6E, 0x6F
SLRC, TRIS_CLK, TRIS_DAT, LAT_CLK, LAT_DAT, PORT_CLK, PORT_DAT = 0, 2, 3, 4, 5, 6, 7
# common RAM
SW, SSTATUS, SBSR, SPCLATH, TXB, CNT, DLYC, RXB, T0, T1 = 0x70, 0x71, 0x72, 0x73, 0x74, 0x75, 0x76, 0x77, 0x78, 0x79

DUMP = [('ICDCON0', ICDCON0), ('ICDSTAT', ICDSTAT), ('ICDIO', ICDIO), ('BSRICDSHAD', BSRICDSHAD),
        ('ICDBK0CON', ICDBK0CON), ('ICDBK0L', ICDBK0L), ('ICDBK0H', ICDBK0H), ('STKPTR', STKPTR), ('TOSL', TOSL), ('TOSH', TOSH),
        ('STATUS_SHAD', STATUS_SHAD), ('WREG_SHAD', WREG_SHAD), ('BSR_SHAD', BSR_SHAD), ('PCLATH_SHAD', PCLATH_SHAD)]
HDR = ['page', 'W', 'STATUS', 'BSR', 'PCLATH']

def exec_copy(a, base, tag, exits, delay=2):
    L = lambda n: f'{n}_{tag}'
    a.org(base)
    a.movwf(SW); a.movf(STATUS, W); a.movwf(SSTATUS); a.movf(BSR, W); a.movwf(SBSR)
    a.movf(PCLATH, W); a.movwf(SPCLATH)
    a.movlp(base >> 8); a.movlb(31)
    a.label(L('dump'))
    a.movlw(0xA0 + tag); a.call(L('tx'))
    for r in (SW, SSTATUS, SBSR, SPCLATH):
        a.movf(r, W); a.call(L('tx'))
    for _, r in DUMP:
        a.movf(r, W); a.call(L('tx'))
    a.label(L('cmd'))
    a.call(L('rx'))
    for ch, lab in (('D', 'dump'), ('R', 'rd'), ('W', 'wr'), ('X', 'ex')):
        a.movf(RXB, W); a.xorlw(ord(ch)); a.btfsc(STATUS, Z); a.goto(L(lab))
    a.goto(L('cmd'))
    # R: addrL addrH -> byte
    a.label(L('rd'))
    a.call(L('rx')); a.movf(RXB, W); a.movwf(FSR0L); a.call(L('rx')); a.movf(RXB, W); a.movwf(FSR0H)
    a.movf(INDF0, W); a.call(L('tx')); a.goto(L('cmd'))
    a.label(L('wr'))
    a.call(L('rx')); a.movf(RXB, W); a.movwf(FSR0L); a.call(L('rx')); a.movf(RXB, W); a.movwf(FSR0H)
    a.call(L('rx')); a.movf(RXB, W); a.movwf(INDF0); a.movlw(0x4B); a.call(L('tx')); a.goto(L('cmd'))
    # X n: exit method n
    a.label(L('ex'))
    a.call(L('rx'))
    a.bsf(ICDIO, TRIS_CLK); a.bsf(ICDIO, TRIS_DAT)
    a.movf(RXB, W); a.brw()
    for i in range(len(exits)):
        a.bra(L(f'exit{i}'))
    for i, seq in enumerate(exits):
        a.label(L(f'exit{i}'))
        seq(a)
        a.bra(L(f'exit{i}_spin')) if False else None
    # tx: W -> probe
    a.label(L('tx'))
    a.movwf(TXB)
    a.call(L('hs'))
    a.movlw(8); a.movwf(CNT)
    a.label(L('txb'))
    a.bcf(ICDIO, LAT_DAT); a.btfsc(TXB, 7); a.bsf(ICDIO, LAT_DAT)
    a.bcf(ICDIO, TRIS_DAT)
    a.bsf(ICDIO, LAT_CLK); a.call(L('dly'))
    a.bcf(ICDIO, LAT_CLK); a.call(L('dly'))
    a.rlf(TXB, F)
    a.decfsz(CNT, F); a.goto(L('txb'))
    a.bsf(ICDIO, TRIS_DAT)
    a.ret()
    # rx: probe -> RXB
    a.label(L('rx'))
    a.call(L('hs'))
    a.movlw(8); a.movwf(CNT)
    a.label(L('rxb'))
    a.bsf(ICDIO, LAT_CLK); a.call(L('dly'))
    a.bcf(ICDIO, LAT_CLK)
    a.rlf(RXB, F); a.bcf(RXB, 0); a.btfsc(ICDIO, PORT_DAT); a.bsf(RXB, 0)
    a.call(L('dly'))
    a.decfsz(CNT, F); a.goto(L('rxb'))
    a.ret()
    # handshake: CLK high, wait DAT low then high, CLK low
    a.label(L('hs'))
    a.bsf(ICDIO, TRIS_DAT)
    a.bsf(ICDIO, LAT_CLK); a.bcf(ICDIO, TRIS_CLK)
    a.label(L('hs1')); a.btfsc(ICDIO, PORT_DAT); a.goto(L('hs1'))
    a.label(L('hs2')); a.btfss(ICDIO, PORT_DAT); a.goto(L('hs2'))
    a.bcf(ICDIO, LAT_CLK)
    a.call(L('dly'))
    a.ret()
    a.label(L('dly'))
    a.movlw(delay); a.movwf(DLYC)
    a.label(L('dly1')); a.decfsz(DLYC, F); a.goto(L('dly1'))
    a.ret()

def restore(a):
    a.movf(SPCLATH, W); a.movwf(PCLATH); a.movf(SBSR, W); a.movwf(BSR)
    a.swapf(SSTATUS, W); a.movwf(STATUS) if False else None
    a.movf(SSTATUS, W); a.movwf(STATUS); a.swapf(SW, F); a.swapf(SW, W)

def build(user, exits, config2=0x2EFF, vector_target=0x700, vector_word=None):
    a = Asm()
    user(a)
    for page in range(4):
        exec_copy(a, 0x700 + 0x800 * page, page, exits)
    words = a.image()
    words[0x8004] = vector_word if vector_word is not None else (0x2800 | vector_target)
    words[0x8007] = 0x09C4      # INTOSC, WDT off, PWRT on, MCLR on
    words[0x8008] = config2
    return words

def user_counter(a):
    a.org(0)
    a.movlb(0); a.clrf(0x20); a.clrf(0x21); a.bra('main')
    a.org(4); a.retfie()
    a.org(0x10)
    a.label('main')
    a.incf(0x20, F)
    a.btfsc(STATUS, Z)
    a.incf(0x21, F)
    a.nop()
    a.bra('main')

class Session:
    def __init__(self, vdd=3300):
        self.p = Probe(); self.vdd = vdd
    def load(self, words, quiet=False):
        p = self.p
        t = Gen6(p, vdd_mv=self.vdd, hvp=True); t.device = identify(0x2480)
        t.enter()
        t.bulk_erase()
        flash, cfg, ee = split_image(t.device, {a: w for a, w in words.items() if a != 0x8004})
        top = max(a for a in words if a < 0x8000) + 1
        top = (top + 7) // 8 * 8
        t.write_flash(flash[:top])
        errs = verify(t, flash, {}, None)
        t.write_config_space({0x8004: words[0x8004]})
        t.write_config_space({a: w for a, w in cfg.items()})
        back = t.read_words(0x8000, 9)
        if not quiet: print('loaded; verify errors %d; config space %s' % (len(errs), ' '.join('%04X' % w for w in back)))
        self.t = t
    def start(self):
        """Leave programming mode with power on; target comes out of reset."""
        self.t.exit(keep_power=True)
    def pins(self):
        return self.p.status()[1]
    def rx(self, n=1, timeout_ms=300):
        try: return self.p.icd_rx(n, timeout_ms)
        except ProbeError as e:
            self.p._queue = []; return None
    def tx(self, data, timeout_ms=300):
        try: self.p.icd_tx(bytes(data), timeout_ms); return True
        except ProbeError as e:
            self.p._queue = []; return False
    def dump(self, first=None):
        n = len(HDR) + len(DUMP)
        d = self.rx(n) if first is None else first
        if d is None: print('  (no dump: executive silent)'); return None
        vals = dict(zip(HDR + [x for x, _ in DUMP], d))
        print('  ' + ' '.join('%s=%02X' % kv for kv in vals.items()))
        return vals
    def read(self, addr):
        self.tx([ord('R'), addr & 0xFF, addr >> 8]); r = self.rx(1); return None if r is None else r[0]
    def write(self, addr, val):
        self.tx([ord('W'), addr & 0xFF, addr >> 8, val]); return self.rx(1)
    def off(self):
        self.p._queue = []; self.p.target_off(); self.p.vdd_mode(VDD_DISCHARGE); self.p.delay_ms(50); self.p.vdd_mode(VDD_OFF); self.p.flush()

# ---- EEPROM logging (independent of the debug pins) ----
EEA = 0x7A
def ee_log_sub(a, name):
    """Subroutine: write W to EEPROM[EEA++].  Leaves BSR = 31."""
    a.label(name)
    a.movlb(3)
    a.movwf(0x13)               # EEDATL
    a.movf(EEA, W); a.movwf(0x11)   # EEADRL
    a.incf(EEA, F)
    a.bcf(0x15, 6); a.bcf(0x15, 7); a.bsf(0x15, 2)
    a.bcf(INTCON, 7)
    a.movlw(0x55); a.movwf(0x16); a.movlw(0xAA); a.movwf(0x16)
    a.bsf(0x15, 1)
    a.bcf(0x15, 2)
    a.label(name + '_w'); a.btfsc(0x15, 1); a.bra(name + '_w')
    a.movlb(31)
    a.ret()

def read_eeprom(s, n=64):
    t = Gen6(s.p, vdd_mv=s.vdd, hvp=True); t.device = identify(0x2480)
    t.enter(); ee = t.read_eeprom(n); t.exit()
    return ee

# ---- RAM persistence channel: RAM survives reset while VDD is held ----
LOG = 0x2120            # linear address of bank 2 GPR 0x120 (FSR linear = 0x2000 + ...)
def lin(bank_addr):     # traditional address -> not used
    return bank_addr

def img_clear():
    a = Asm(); a.org(0); a.movlp(0); a.goto('s'); a.org(4); a.retfie(); a.org(0x10); a.label('s')
    a.movlw(0x20); a.movwf(FSR0L); a.movlw(0x01); a.movwf(FSR0H)     # traditional 0x120
    a.movlw(0x30); a.movwf(CNT)
    a.label('c'); a.movlw(0x00); a.movwi_postinc(0); a.decfsz(CNT, F); a.bra('c')
    a.label('z'); a.bra('z')
    w = a.image(); w[0x8007] = 0x09C4; w[0x8008] = 0x3EFF; return w

def img_dump(n=0x30):
    a = Asm(); a.org(0); a.movlp(0); a.goto('s'); a.org(4); a.retfie(); a.org(0x10); a.label('s')
    a.movlw(0x20); a.movwf(FSR0L); a.movlw(0x01); a.movwf(FSR0H)
    a.clrf(EEA); a.movlw(n); a.movwf(T0)
    a.label('d'); a.moviw_postinc(0); a.call('log'); a.decfsz(T0, F); a.bra('d')
    a.label('z'); a.bra('z')
    ee_log_sub(a, 'log')
    w = a.image(); w[0x8007] = 0x09C4; w[0x8008] = 0x3EFF; return w

class Lab:
    """Keeps target power on across reprogramming so RAM contents survive."""
    def __init__(self, vdd=3300):
        self.p = Probe(); self.vdd = vdd; self.first = True
    def load(self, words):
        t = Gen6(self.p, vdd_mv=self.vdd, hvp=self.first); t.device = identify(0x2480)
        self.first = False
        t.enter(); t.bulk_erase()
        flash, cfg, ee = split_image(t.device, {a: w for a, w in words.items() if a != 0x8004})
        top = (max(a for a in words if a < 0x8000) + 8) // 8 * 8
        t.write_flash(flash[:top])
        errs = verify(t, flash, {}, None)
        if 0x8004 in words: t.write_config_space({0x8004: words[0x8004]})
        t.write_config_space(cfg)
        back = t.read_words(0x8004, 5)
        assert not errs and back[4] == words[0x8008], (errs[:3], back)
        t.exit(keep_power=True)
    def read_ee(self, n):
        t = Gen6(self.p, vdd_mv=self.vdd, hvp=False); t.device = identify(0x2480)
        t.enter(); ee = t.read_eeprom(n); t.exit(keep_power=True); return ee
    def pins(self): return self.p.status()[1]
    def ram_after(self, image, stimulus=None, run=0.3, n=0x30):
        self.load(img_clear()); time.sleep(0.1)
        self.load(image); time.sleep(run)
        pins = self.pins()
        if stimulus: stimulus(self.p); time.sleep(0.1)
        pins2 = self.pins()
        self.p.pins(PINS_IDLE); self.p.flush()
        self.load(img_dump(n)); time.sleep(0.6)
        return self.read_ee(n), pins, pins2
    def off(self):
        self.p._queue = []; self.p.target_off(); self.p.vdd_mode(VDD_DISCHARGE); self.p.delay_ms(50); self.p.vdd_mode(VDD_OFF); self.p.flush(); self.p.close()

# ---- executive in the debug space 0x8010-0x80FF ----
DBG_LO, DBG_HI = 0x8010, 0x8100
DBG_ROWS = [0x8020, 0x8040, 0x8060, 0x8080, 0x80A0, 0x80C0, 0x80E0]

def lab_load(self, words):
    t = Gen6(self.p, vdd_mv=self.vdd, hvp=self.first); t.device = identify(0x2480); self.first = False
    t.enter(); t.bulk_erase()
    for r in DBG_ROWS:
        t._seek(r); self.p.queue([OP_G6_CMD, Gen6.ERASE_ROW]); self.p.delay_ms(6)
    self.p.flush()
    dbg = {a: w for a, w in words.items() if a in (0x8004, 0x8005) or 0x800B <= a < DBG_HI}
    assert not any(a >= DBG_HI and a < 0x8200 for a in words), 'image touches protected debug space'
    flash, cfg, ee = split_image(t.device, {a: w for a, w in words.items() if a not in dbg})
    top = (max([a for a in words if a < 0x8000] + [0]) + 8) // 8 * 8
    t.write_flash(flash[:top]); assert not verify(t, flash, {}, None)
    if dbg:
        t.write_config_space(dbg)
        lo, hi = min(dbg), max(dbg)
        back = t.read_words(lo, hi - lo + 1)
        bad = [hex(a) for a in dbg if back[a - lo] != dbg[a]]
        assert not bad, ('debug space verify', bad[:5])
    t.write_config_space(cfg)
    assert t.read_words(0x8008, 1)[0] == words[0x8008]
    t.exit(keep_power=True)
Lab.load = lab_load

def lab_cleanup(self):
    """Erase everything including the debug space, leave the chip blank."""
    t = Gen6(self.p, vdd_mv=self.vdd, hvp=True); t.device = identify(0x2480)
    t.enter(); t.bulk_erase()
    for r in DBG_ROWS:
        t._seek(r); self.p.queue([OP_G6_CMD, Gen6.ERASE_ROW]); self.p.delay_ms(6)
    self.p.flush(); t.exit()
Lab.cleanup = lab_cleanup

# ---- larger linear RAM log: linear 0x20A0 = bank 2 0x120, runs on through bank 3 ----
LOGN = 0xA0
def _img(body):
    a = Asm(); a.org(0); a.movlp(0); a.goto('s'); a.org(4); a.retfie(); a.org(0x10); a.label('s')
    a.movlw(0xA0); a.movwf(FSR0L); a.movlw(0x20); a.movwf(FSR0H)
    body(a)
    a.label('z'); a.bra('z')
    return a
def img_clear():
    def body(a):
        a.movlw(LOGN); a.movwf(CNT)
        a.label('c'); a.movlw(0x00); a.movwi_postinc(0); a.decfsz(CNT, F); a.bra('c')
    w = _img(body).image(); w[0x8007] = 0x09C4; w[0x8008] = 0x3EFF; return w
def img_dump(n=LOGN):
    def body(a):
        a.clrf(EEA); a.movlw(n); a.movwf(T0)
        a.label('d'); a.moviw_postinc(0); a.call('log'); a.decfsz(T0, F); a.bra('d')
    a = _img(body); ee_log_sub(a, 'log')
    w = a.image(); w[0x8007] = 0x09C4; w[0x8008] = 0x3EFF; return w
def ram_after(self, image, stimulus=None, run=0.3, n=LOGN):
    self.load(img_clear()); time.sleep(0.1)
    self.load(image); time.sleep(run)
    pins = self.pins()
    if stimulus: stimulus(self); time.sleep(0.1)
    pins2 = self.pins()
    self.p.pins(PINS_IDLE); self.p.flush()
    self.load(img_dump(n)); time.sleep(0.3 + n * 0.006)
    return self.read_ee(n), pins, pins2
Lab.ram_after = ram_after
def log_ptr(a, off=0x10):
    a.movlw(0xA0 + off); a.movwf(FSR1L); a.movlw(0x20); a.movwf(FSR1H)
def log_w(a): a.movwi_postinc(1)
def log_lit(a, k): a.movlw(k); a.movwi_postinc(1)
def log_reg(a, r): a.movf(r, W); a.movwi_postinc(1)
def user_std(a):
    a.org(0); a.movlp(0); a.goto('u'); a.org(4); a.retfie(); a.org(0x10); a.label('u')
    a.movlb(2); a.movlw(0x55); a.movwf(0x20)
    a.label('ul'); a.incf(0x21, F); a.bra('ul')
def dbg_image(body, user=user_std, cfg2=0x2EFF):
    a = Asm(); user(a); a.org(0x8010); body(a); w = a.image()
    n = sum(1 for x in w if x >= 0x8010); assert max(w) < 0x8100, 'executive too big: %d' % n
    w[0x8004] = 0x2810; w[0x8007] = 0x09C4; w[0x8008] = cfg2
    return w
def hexs(b): return ' '.join('%02X' % x for x in b)

# ---- real register layout found on the PIC16LF1937 ----
R_PIN, R_PINLAT, R_CON, R_PCL, R_PCH = 0x0C, 0x0D, 0x0E, 0x10, 0x11      # 0xF8C, 0xF8D, 0xF8E, 0xF90, 0xF91
def entry_logger(a, extra=()):
    """Count entries at 0x123 and log (F90, F91, F8E, x) for the first 16 into 0x130.."""
    a.movlw(0xA3); a.movwf(FSR0L); a.movlw(0x20); a.movwf(FSR0H)
    a.incf(INDF0, F)
    a.movf(INDF0, W); a.addlw(0xEF); a.btfsc(STATUS, C); a.goto('nolog')      # count >= 17
    a.movf(INDF0, W); a.addwf(INDF0, W); a.movwf(T0); a.addwf(T0, W); a.addlw(0xAC)
    a.movwf(FSR1L); a.movlw(0x20); a.movwf(FSR1H)
    a.movlb(31)
    for r in (R_PCL, R_PCH, R_CON) + tuple(extra): log_reg(a, r)
    a.label('nolog')
    a.movlb(31)
def show_entries(ee, n=16, cols=4):
    print('  user marker %02X, user count %02X, entries %d' % (ee[0], ee[1], ee[3]))
    rows = [ee[0x10 + cols*i: 0x10 + cols*i + cols] for i in range(min(n, ee[3]))]
    print('  per entry (F90 F91 F8E ..): ' + ' | '.join(hexs(r) for r in rows))

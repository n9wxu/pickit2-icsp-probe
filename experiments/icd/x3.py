from icdx import *
PINV = (0x30, 0x31, 0x32, 0x33, 0x11, 0x21, 0x13, 0x23, 0x03)
REGS = [0x0D, 0x0F] + list(range(0x12, 0x20)) + [0x10, 0x11, 0x0E]
def body(a):
    log_ptr(a, 0x10)
    a.movlb(31)
    for v in PINV:
        a.movlw(v); a.movwf(0x0C); a.nop(); log_reg(a, 0x0C)
    a.movlw(0x0C); a.movwf(0x0C)                      # pins back to inputs
    for r in REGS:
        log_reg(a, r); a.movlw(0xFF); a.movwf(r); log_reg(a, r); a.clrf(r); log_reg(a, r)
    log_lit(a, 0xEE)
    a.label('spin'); a.movlb(2); a.incf(0x22, F); a.goto('spin')
img = dbg_image(body)
print('executive size %d words' % sum(1 for x in img if x >= 0x8010))
lab = Lab()
ee, pins, _ = lab.ram_after(img)
print('user [120..122]:', hexs(ee[0:3]), ' pins %02x' % pins)
print('pin register read-back (bit7 DAT pin, bit6 CLK pin, bits 3:2 TRIS):')
for v, r in zip(PINV, ee[0x10:]): print('   wrote %02X -> read %02X' % (v, r))
o = 0x10 + len(PINV)
print('register: original / after FF / after 00')
for i, r in enumerate(REGS):
    print('   0x%03X: %s' % (0xF80 + r, hexs(ee[o + 3*i: o + 3*i + 3])))
print('end marker:', '%02X' % ee[o + 3*len(REGS)])
lab.off()

from icdx import *
def body(a):
    log_ptr(a, 0x10)
    a.movlb(31)
    for r in range(0x0C, 0x20): log_reg(a, r)          # 0xF8C..0xF9F -> log[0x10..0x23]
    for r in range(0x60, 0x70): log_reg(a, r)          # 0xFE0..0xFEF -> log[0x24..0x33]
    # write tests on 0xF8C
    for v in (0xFF, 0x00, 0x30, 0xF3):
        a.movlw(v); a.movwf(0x0C); log_reg(a, 0x0C)     # log[0x34..0x37]
    a.label('spin'); a.goto('spin')
lab = Lab()
ee, pins, _ = lab.ram_after(dbg_image(body))
print('pins after final write of F3 to 0xF8C: %02x  (bit0 DAT, bit2 CLK)' % pins)
print('0xF8C..0xF9F:', hexs(ee[0x10:0x24]))
print('0xFE0..0xFEF:', hexs(ee[0x24:0x34]))
print('0xF8C after writing FF, 00, 30, F3:', hexs(ee[0x34:0x38]))
lab.off()

from icdx import *
from e3lib import *
# Lab.load must also write 0x8005
_old = Lab.load
def load(self, words):
    t = Gen6(self.p, vdd_mv=self.vdd, hvp=self.first); t.device = identify(0x2480); self.first = False
    t.enter(); t.bulk_erase()
    flash, cfg, ee = split_image(t.device, {a: w for a, w in words.items() if a not in (0x8004, 0x8005)})
    top = (max(a for a in words if a < 0x8000) + 8) // 8 * 8
    t.write_flash(flash[:top]); assert not verify(t, flash, {}, None)
    t.write_config_space({a: words[a] for a in (0x8004, 0x8005) if a in words})
    t.write_config_space(cfg)
    assert t.read_words(0x8008, 1)[0] == words[0x8008]
    t.exit(keep_power=True)
Lab.load = load
lab = Lab()
tests = [('RETURN', 0x0008, None), ('RETFIE', 0x0009, None), ('MOVLP 7 ; CLRF PCL', 0x3187, 0x0182),
         ('MOVLP 7 ; CALLW', 0x3187, 0x000A), ('NOP ; NOP (fall through)', 0x0000, 0x0000)]
for name, v1, v2 in tests:
    ee, pins, _ = lab.ram_after(image(0x2EFF, v1, v2))
    ex = ee[0x10:0x1F]
    print('%-26s pins %02x  user ran: %s (count %02X)  exec: %s' % (name, pins, 'YES' if ee[0] == 0x55 else 'no', ee[1],
          'not reached' if ex[0] == 0 else ' '.join('%s=%02X' % kv for kv in zip(names, ex))), ' exec count %02X' % ee[2])
lab.off()

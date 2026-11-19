from icdx import *
import pickle
base = pickle.load(open('cfgspace.pkl', 'rb'))[:0x200]
p = Probe(); t = Gen6(p, vdd_mv=3300, hvp=True); t.device = identify(0x2480); t.enter()
print('0x8020 row before:', ' '.join('%04X' % x for x in t.read_words(0x8020, 8)))
t._seek(0x8020)
p.queue([OP_G6_CMD, Gen6.ERASE_ROW]); p.delay_ms(6); p.flush()
print('0x8020 row after row erase:', ' '.join('%04X' % x for x in t.read_words(0x8020, 8)))
w = t.read_words(0x8000, 0x200)
diff = [(0x8000 + i, base[i], w[i]) for i in range(0x200) if w[i] != base[i]]
print('differences from the original map:', [('%04X' % a, '%04X->%04X' % (b, c)) for a, b, c in diff])
t.exit(); p.close()

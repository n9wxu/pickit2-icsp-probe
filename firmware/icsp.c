/*
 * ICSP bit transfers and the debug-executive link.
 *
 * Programming: the probe drives ICSPCLK.  Data changes on the rising edge
 * and is latched by the receiver on the falling edge.
 *
 * Debug link: the roles are reversed.  The debug executive running on the
 * target drives the clock at whatever speed its oscillator allows and the
 * probe follows, after a handshake:
 *
 *   target raises CLK        "ready for a byte"
 *   probe pulses DAT low for 800 us, then drives it high
 *   target lowers CLK
 *   8 clock pulses from the target, MSB first.  When the probe transmits,
 *   it changes DAT while CLK is high and the target samples after the
 *   falling edge.  When the probe receives, the target changes DAT while CLK
 *   is high and the probe samples after the falling edge.
 */
#include "hw.h"
#include "icsp.h"

static uint8_t extra_delay;

void icsp_set_speed(uint8_t n)
{
    extra_delay = n;
}

/* Half a clock period.  With extra_delay = 0 it is about 0.5 us. */
static void half_bit(void)
{
    uint8_t n = extra_delay;

    while (n--)
        _delay(8);
}

#define CLOCK_PULSE()  do { ICSPCLK_OUT = 1; half_bit(); \
                            ICSPCLK_OUT = 0; half_bit(); } while (0)

void icsp_pins(uint8_t v)
{
    ICSPDAT_OUT  = (v & ICSP_PIN_DAT) ? 1 : 0;
    ICSPCLK_OUT  = (v & ICSP_PIN_CLK) ? 1 : 0;
    ICSPDAT_TRIS = (v & ICSP_PIN_DAT_IN) ? 1 : 0;
    ICSPCLK_TRIS = (v & ICSP_PIN_CLK_IN) ? 1 : 0;
}

uint8_t icsp_pin_state(void)
{
    uint8_t v = 0;

    if (ICSPDAT_IN)   v |= ICSP_PIN_DAT;
    if (ICSPDAT_TRIS) v |= ICSP_PIN_DAT_IN;
    if (ICSPCLK_IN)   v |= ICSP_PIN_CLK;
    if (ICSPCLK_TRIS) v |= ICSP_PIN_CLK_IN;
    return v;
}

void icsp_out_lsb(uint8_t v, uint8_t n)
{
    ICSPDAT_TRIS = 0;
    do {
        if (v & 1) ICSPDAT_OUT = 1; else ICSPDAT_OUT = 0;
        v >>= 1;
        CLOCK_PULSE();
    } while (--n);
}

void icsp_out_msb(uint8_t v, uint8_t n)
{
    ICSPDAT_TRIS = 0;
    do {
        if (v & 0x80) ICSPDAT_OUT = 1; else ICSPDAT_OUT = 0;
        v <<= 1;
        CLOCK_PULSE();
    } while (--n);
}

uint8_t icsp_in_lsb(uint8_t n)
{
    uint8_t v = 0, mask = 1;

    ICSPDAT_TRIS = 1;
    do {
        ICSPCLK_OUT = 1;
        half_bit();
        _delay(2);
        if (ICSPDAT_IN) v |= mask;
        ICSPCLK_OUT = 0;
        half_bit();
        mask <<= 1;
    } while (--n);
    return v;
}

uint8_t icsp_in_msb(uint8_t n)
{
    uint8_t v = 0;

    ICSPDAT_TRIS = 1;
    do {
        v <<= 1;
        ICSPCLK_OUT = 1;
        half_bit();
        _delay(2);
        if (ICSPDAT_IN) v |= 1;
        ICSPCLK_OUT = 0;
        half_bit();
    } while (--n);
    return v;
}

/* ---- 6 bit command generation (PIC16F1xxx): LSB first ---------------- */

void g6_cmd(uint8_t c)
{
    icsp_out_lsb(c, 6);
    _delay(24);                 /* Tdly >= 1 us */
}

void g6_load(uint8_t c, uint16_t w)
{
    g6_cmd(c);
    w = (w << 1) & 0x7FFE;      /* start bit, 14 data bits, stop bit */
    icsp_out_lsb((uint8_t)w, 8);
    icsp_out_lsb((uint8_t)(w >> 8), 8);
    _delay(24);
}

uint16_t g6_read(uint8_t c)
{
    uint16_t w;

    g6_cmd(c);
    w = icsp_in_lsb(8);
    w |= (uint16_t)icsp_in_lsb(8) << 8;
    _delay(24);
    return (w >> 1) & 0x3FFF;
}

/* ---- 8 bit command generation (PIC16F1xxxx, PIC18F-Q): MSB first ----- */

void g8_cmd(uint8_t c)
{
    icsp_out_msb(c, 8);
    _delay(24);
}

void g8_write(uint8_t c, uint8_t b2, uint8_t b1, uint8_t b0)
{
    g8_cmd(c);
    icsp_out_msb(b2, 8);
    icsp_out_msb(b1, 8);
    icsp_out_msb(b0, 8);
    _delay(24);
}

void g8_read(uint8_t c, uint8_t *p)
{
    g8_cmd(c);
    p[0] = icsp_in_msb(8);
    p[1] = icsp_in_msb(8);
    p[2] = icsp_in_msb(8);
    _delay(24);
}

/* ---- Debug-executive link ------------------------------------------- */

static void timeout_start(uint8_t t10ms)
{
    uint16_t count = (uint16_t)(0u - (uint16_t)t10ms * 469u);  /* 46875 Hz */

    T0CON = 0x07;               /* 16 bit, Fosc/4, 1:256, stopped */
    TMR0H = (uint8_t)(count >> 8);
    TMR0L = (uint8_t)count;
    INTCONbits.TMR0IF = 0;
    T0CONbits.TMR0ON = 1;
}

#define TIMED_OUT()  (INTCONbits.TMR0IF)

static uint8_t icd_handshake(uint8_t t10ms)
{
    power_pump_pause();
    INTCONbits.GIE = 0;
    ICSPCLK_TRIS = 1;
    timeout_start(t10ms);

    while (!ICSPCLK_IN)
        if (TIMED_OUT()) return 1;
    ICSPDAT_OUT = 0;
    ICSPDAT_TRIS = 0;
    __delay_us(800);
    ICSPDAT_OUT = 1;
    while (ICSPCLK_IN)
        if (TIMED_OUT()) return 1;
    return 0;
}

static void icd_finish(void)
{
    T0CONbits.TMR0ON = 0;
    INTCONbits.GIE = 1;
    power_pump_resume();
}

uint8_t icd_ready(void)
{
    return (ICSPCLK_TRIS && ICSPCLK_IN) ? 1 : 0;
}

uint8_t icd_tx(uint8_t b, uint8_t t10ms)
{
    uint8_t i, err = 1;

    if (icd_handshake(t10ms))
        goto done;
    for (i = 8; i; i--) {
        while (!ICSPCLK_IN)
            if (TIMED_OUT()) goto done;
        if (b & 0x80) ICSPDAT_OUT = 1; else ICSPDAT_OUT = 0;
        b <<= 1;
        while (ICSPCLK_IN)
            if (TIMED_OUT()) goto done;
    }
    err = 0;
done:
    /* DAT stays driven so a slow target does not miss the last bit. */
    icd_finish();
    return err;
}

uint8_t icd_rx(uint8_t *b, uint8_t t10ms)
{
    uint8_t i, v = 0, err = 1;

    if (icd_handshake(t10ms))
        goto done;
    ICSPDAT_TRIS = 1;
    for (i = 8; i; i--) {
        while (!ICSPCLK_IN)
            if (TIMED_OUT()) goto done;
        while (ICSPCLK_IN)
            if (TIMED_OUT()) goto done;
        v <<= 1;
        if (ICSPDAT_IN) v |= 1;
    }
    err = 0;
done:
    /* Drive DAT high so a floating line is not taken for a handshake. */
    ICSPDAT_OUT = 1;
    ICSPDAT_TRIS = 0;
    *b = v;
    icd_finish();
    return err;
}

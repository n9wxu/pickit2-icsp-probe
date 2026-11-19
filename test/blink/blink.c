/*
 * Programming test image for the F1 Evaluation Platform (PIC16LF1937).
 * Counts on the four LEDs (RE0, RE1, RE2, RD1) about twice a second.
 * It carries EEPROM data and user IDs so that one image exercises every
 * memory region, and it enables low-voltage programming.
 */
#include <xc.h>
#include <stdint.h>

#pragma config FOSC = INTOSC, WDTE = OFF, PWRTE = ON, MCLRE = ON
#pragma config CP = OFF, CPD = OFF, BOREN = OFF, CLKOUTEN = OFF
#pragma config IESO = OFF, FCMEN = OFF
#pragma config WRT = OFF, PLLEN = OFF, STVREN = ON
#pragma config BORV = LO, LVP = ON
#pragma config IDLOC0 = 0x01, IDLOC1 = 0x02, IDLOC2 = 0x03, IDLOC3 = 0x04

#define _XTAL_FREQ 500000UL

__EEPROM_DATA('p', 'k', '2', 'p', 'r', 'o', 'b', 'e');
__EEPROM_DATA(0x00, 0x11, 0x22, 0x33, 0x44, 0x55, 0x66, 0x77);

/* Fill part of the flash with a pattern so a verify covers many rows. */
const uint8_t pattern[512] = {
#define R4(n)  (n), (uint8_t)((n) * 7 + 1), (uint8_t)((n) * 13 + 5), (uint8_t)~(n)
#define R16(n) R4(n), R4((n) + 1), R4((n) + 2), R4((n) + 3)
#define R64(n) R16(n), R16((n) + 4), R16((n) + 8), R16((n) + 12)
    R64(0), R64(16), R64(32), R64(48), R64(64), R64(80), R64(96), R64(112)
};

void main(void)
{
    uint8_t n = 0;

    ANSELD = 0;
    ANSELE = 0;
    LATD = 0;
    LATE = 0;
    TRISDbits.TRISD1 = 0;
    TRISE = 0xF8;

    for (;;) {
        LATE = (uint8_t)(n & 0x07);
        LATDbits.LATD1 = (n >> 3) & 1;
        n += pattern[n & 0x01] ? 1 : 1;
        __delay_ms(500);
    }
}

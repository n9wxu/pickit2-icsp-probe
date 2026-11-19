/*
 * PICkit 2 ICSP probe firmware.
 *
 * Runs above the factory PICkit 2 bootloader, which occupies 0x0000-0x1FFF
 * and starts the application at 0x2000 when the byte at 0x7FFE is 0x55 and
 * the button is not held at power-up.
 */
#include "hw.h"
#include "usb.h"
#include "icsp.h"
#include "proto.h"

/*
 * Configuration bits are owned by the bootloader and cannot be changed
 * through it.  They are repeated here so that a combined image programmed
 * through the ICSP header carries the same settings.
 */
#pragma config PLLDIV = 5, CPUDIV = OSC1_PLL2, USBDIV = 2
#pragma config FOSC = HSPLL_HS, FCMEN = OFF, IESO = OFF
#pragma config PWRT = ON, BOR = OFF, BORV = 3, VREGEN = ON
#pragma config WDT = OFF, WDTPS = 32768
#pragma config MCLRE = OFF, LPT1OSC = OFF, PBADEN = OFF, CCP2MX = ON
#pragma config STVREN = ON, LVP = OFF, XINST = OFF
#pragma config CP0 = OFF, CP1 = OFF, CP2 = OFF, CP3 = OFF, CPB = OFF, CPD = OFF
#pragma config WRT0 = ON, WRT1 = OFF, WRT2 = OFF, WRT3 = OFF
#pragma config WRTB = ON, WRTC = OFF, WRTD = OFF
#pragma config EBTR0 = OFF, EBTR1 = OFF, EBTR2 = OFF, EBTR3 = OFF, EBTRB = OFF

/*
 * Development failsafe.  The application returns to the bootloader by itself
 * when it was reset by the watchdog or a stack fault, or when the host has
 * not configured it within ENUM_TIMEOUT_MS of start-up.  This makes a bad
 * build recoverable without pressing the button.  Build with
 * -DDEV_FAILSAFE=0 for a probe that must also start on a charger.
 */
#ifndef DEV_FAILSAFE
#define DEV_FAILSAFE 1
#endif
#define ENUM_TIMEOUT_MS 20000u

#define BOOT_KEY_BLOCK  0x7FC0u

static uint8_t reply[USB_PKT_SIZE];
static uint8_t reply_len;

void __interrupt() isr(void)
{
    power_isr();
}

void delay_us(uint16_t us)
{
    while (us--)
        _delay(5);              /* about 1 us per pass with the loop overhead */
}

void delay_ms(uint16_t ms)
{
    while (ms--) {
        __delay_ms(1);
        CLRWDT();
    }
}

static void target_safe(void)
{
    power_mclr(0);
    power_set_vpp(0);
    power_vdd_mode(0);
    icsp_pins(ICSP_PIN_DAT_IN | ICSP_PIN_CLK_IN);
}

void hw_init(void)
{
    /* Port A: ICSP pins tristated, MCLR released. */
    LATA = 0x00;
    TRISA = 0xDF;               /* RA5 output, the rest inputs */
    CMCON = 0x07;               /* comparators off */
    CVRCON = 0x00;

    /* Port B: VDD half bridge off, VPP switch off, pull-up for the button. */
    LATB = 0x10;                /* VDD P gate high = off */
    TRISB = 0xE3;               /* RB2, RB3, RB4 outputs */
    INTCON2bits.RBPU = 0;

    /* Port C: LED, boost switch, VDD reference, EEPROM write protect. */
    LATC = 0x40;
    TRISC = 0xB8;               /* RC0, RC1, RC2, RC6 outputs */
}

/* Erase the block holding the bootloader's "application valid" key, then
 * reset.  The bootloader stays in control until an image is loaded again. */
void enter_bootloader(void)
{
    INTCONbits.GIE = 0;
    target_safe();
    CCP1CON = 0;

    TBLPTRU = 0;
    TBLPTRH = (uint8_t)(BOOT_KEY_BLOCK >> 8);
    TBLPTRL = (uint8_t)BOOT_KEY_BLOCK;
    EECON1 = 0x94;              /* EEPGD, FREE, WREN */
    EECON2 = 0x55;
    EECON2 = 0xAA;
    EECON1bits.WR = 1;
    NOP();
    EECON1 = 0;

    UCON = 0;                   /* detach so the host sees a new device */
    delay_ms(300);
    RESET();
}

uint8_t app_info(uint8_t *buf)
{
    buf[0] = 'P';
    buf[1] = 'K';
    buf[2] = '2';
    buf[3] = 'P';
    buf[4] = FW_VERSION_MAJOR;
    buf[5] = FW_VERSION_MINOR;
    buf[6] = PROTO_VERSION;
    buf[7] = CAP_HVP | CAP_VDD_SOURCE | CAP_GEN6 | CAP_GEN8 | CAP_ICD;
    return 8;
}

static void put16(uint16_t v)
{
    reply[reply_len++] = (uint8_t)v;
    reply[reply_len++] = (uint8_t)(v >> 8);
}

#define NEED(n)   do { if ((uint8_t)(len - i) < (n)) { err = ERR_TRUNCATED; goto out; } } while (0)
#define ROOM(n)   do { if ((uint8_t)(USB_PKT_SIZE - reply_len) < (n)) { err = ERR_OVERFLOW; goto out; } } while (0)
#define ARG(k)    (usb_rx_buf[i + (k)])
#define ARG16(k)  ((uint16_t)ARG(k) | ((uint16_t)ARG((k) + 1) << 8))

static uint8_t deferred;        /* action to take after the reply is sent */

static void process(uint8_t len)
{
    uint8_t i = 0, err = ERR_OK, op_at = 0;
    uint8_t n, k, flags;

    reply_len = 2;
    deferred = 0;

    while (i < len) {
        uint8_t op = ARG(0);

        op_at = i;
        i++;
        switch (op) {
        case OP_END:
            goto out;

        case OP_INFO:
            ROOM(8);
            reply_len += app_info(&reply[reply_len]);
            break;

        case OP_STATUS:
            ROOM(2);
            reply[reply_len++] = power_status();
            reply[reply_len++] = icsp_pin_state();
            break;

        case OP_READ_VOLT: {
            uint16_t rv, rp;

            ROOM(8);
            put16(power_read_vdd_mv());
            put16(power_read_vpp_mv());
            power_read_raw(&rv, &rp);
            put16(rv);
            put16(rp);
            break;
        }

        case OP_SET_VDD:
            NEED(2);
            if (power_set_vdd(ARG16(0))) { err = ERR_RANGE; goto out; }
            i += 2;
            break;

        case OP_VDD_MODE:
            NEED(1);
            if (ARG(0) > 2) { err = ERR_RANGE; goto out; }
            power_vdd_mode(ARG(0));
            i += 1;
            break;

        case OP_SET_VPP:
            NEED(2);
            if (power_set_vpp(ARG16(0))) { err = ERR_RANGE; goto out; }
            i += 2;
            break;

        case OP_MCLR:
            NEED(1);
            if (ARG(0) > 2) { err = ERR_RANGE; goto out; }
            power_mclr(ARG(0));
            i += 1;
            break;

        case OP_PINS:
            NEED(1);
            ROOM(1);
            icsp_pins(ARG(0));
            _delay(12);
            reply[reply_len++] = icsp_pin_state();
            i += 1;
            break;

        case OP_DELAY_US:
            NEED(2);
            delay_us(ARG16(0));
            i += 2;
            break;

        case OP_DELAY_MS:
            NEED(1);
            delay_ms(ARG(0));
            i += 1;
            break;

        case OP_SPEED:
            NEED(1);
            icsp_set_speed(ARG(0));
            i += 1;
            break;

        case OP_LED:
            NEED(1);
            LED = ARG(0) ? 1 : 0;
            i += 1;
            break;

        case OP_CLEAR_FAULTS:
            power_clear_faults();
            break;

        case OP_BOOTLOADER:
            NEED(2);
            if (ARG(0) != 'B' || ARG(1) != 'L') { err = ERR_RANGE; goto out; }
            deferred = OP_BOOTLOADER;
            i += 2;
            goto out;

        case OP_RESET:
            NEED(2);
            if (ARG(0) != 'R' || ARG(1) != 'S') { err = ERR_RANGE; goto out; }
            deferred = OP_RESET;
            i += 2;
            goto out;

        case OP_WRITE_BITS:
            NEED(2);
            n = ARG(0);
            flags = ARG(1);
            if (n == 0 || n > 32) { err = ERR_RANGE; goto out; }
            k = (uint8_t)((n + 7) >> 3);
            NEED((uint8_t)(2 + k));
            i += 2;
            while (n) {
                uint8_t bits = n > 8 ? 8 : n;

                if (flags & BITS_MSB_FIRST)
                    icsp_out_msb(ARG(0), bits);
                else
                    icsp_out_lsb(ARG(0), bits);
                n -= bits;
                i++;
            }
            break;

        case OP_READ_BITS:
            NEED(2);
            n = ARG(0);
            flags = ARG(1);
            if (n == 0 || n > 32) { err = ERR_RANGE; goto out; }
            ROOM((uint8_t)((n + 7) >> 3));
            i += 2;
            while (n) {
                uint8_t bits = n > 8 ? 8 : n;

                if (flags & BITS_MSB_FIRST)
                    reply[reply_len++] = (uint8_t)(icsp_in_msb(bits) << (8 - bits));
                else
                    reply[reply_len++] = icsp_in_lsb(bits);
                n -= bits;
            }
            break;

        case OP_KEY:
            NEED(6);
            flags = ARG(0);
            for (k = 1; k <= 4; k++) {
                if (flags & BITS_MSB_FIRST)
                    icsp_out_msb(ARG(k), 8);
                else
                    icsp_out_lsb(ARG(k), 8);
            }
            n = ARG(5);
            if (n > 8) { err = ERR_RANGE; goto out; }
            if (n)
                icsp_out_lsb(0, n);
            i += 6;
            break;

        case OP_EE_READ:
            NEED(2);
            n = ARG(1);
            ROOM(n);
            for (k = 0; k < n; k++)
                reply[reply_len++] = ee_read((uint8_t)(ARG(0) + k));
            i += 2;
            break;

        case OP_EE_WRITE:
            NEED(2);
            n = ARG(1);
            NEED((uint8_t)(2 + n));
            for (k = 0; k < n; k++)
                ee_write((uint8_t)(ARG(0) + k), ARG(2 + k));
            power_load_cal();
            i += (uint8_t)(2 + n);
            break;

        case OP_G6_CMD:
            NEED(1);
            g6_cmd(ARG(0));
            i += 1;
            break;

        case OP_G6_LOAD:
            NEED(3);
            g6_load(ARG(0), ARG16(1));
            i += 3;
            break;

        case OP_G6_READ:
            NEED(1);
            ROOM(2);
            put16(g6_read(ARG(0)));
            i += 1;
            break;

        case OP_G6_READN:
            NEED(3);
            n = ARG(2);
            if (n > 31) { err = ERR_RANGE; goto out; }
            ROOM((uint8_t)(n << 1));
            while (n--) {
                put16(g6_read(ARG(0)));
                g6_cmd(ARG(1));
            }
            i += 3;
            break;

        case OP_G6_LOADN:
            NEED(3);
            n = ARG(2);
            if (n == 0 || n > 29) { err = ERR_RANGE; goto out; }
            NEED((uint8_t)(3 + (n << 1)));
            for (k = 0; k < n; k++) {
                g6_load(ARG(0), ARG16(3 + (k << 1)));
                if (k != n - 1)
                    g6_cmd(ARG(1));
            }
            i += (uint8_t)(3 + (n << 1));
            break;

        case OP_G8_CMD:
            NEED(1);
            g8_cmd(ARG(0));
            i += 1;
            break;

        case OP_G8_WRITE:
            NEED(4);
            g8_write(ARG(0), ARG(1), ARG(2), ARG(3));
            i += 4;
            break;

        case OP_G8_READ:
            NEED(1);
            ROOM(3);
            g8_read(ARG(0), &reply[reply_len]);
            reply_len += 3;
            i += 1;
            break;

        case OP_G8_READN: {
            uint8_t p[3];

            NEED(2);
            n = ARG(1);
            if (n > 31) { err = ERR_RANGE; goto out; }
            ROOM((uint8_t)(n << 1));
            while (n--) {
                g8_read(ARG(0), p);
                reply[reply_len++] = (uint8_t)((p[2] >> 1) | (p[1] << 7));
                reply[reply_len++] = (uint8_t)((p[1] >> 1) | (p[0] << 7));
            }
            i += 2;
            break;
        }

        case OP_G8_LOADN:
            NEED(3);
            n = ARG(2);
            if (n == 0 || n > 29) { err = ERR_RANGE; goto out; }
            NEED((uint8_t)(3 + (n << 1)));
            for (k = 0; k < n; k++) {
                uint8_t lo = ARG(3 + (k << 1));
                uint8_t hi = ARG(4 + (k << 1));

                g8_write(k == n - 1 ? ARG(1) : ARG(0),
                         (uint8_t)(hi >> 7),
                         (uint8_t)((hi << 1) | (lo >> 7)),
                         (uint8_t)(lo << 1));
            }
            i += (uint8_t)(3 + (n << 1));
            break;

        case OP_ICD_READY:
            ROOM(1);
            reply[reply_len++] = icd_ready();
            break;

        case OP_ICD_TX:
            NEED(2);
            n = ARG(1);
            NEED((uint8_t)(2 + n));
            for (k = 0; k < n; k++) {
                if (icd_tx(ARG(2 + k), ARG(0))) { err = ERR_TIMEOUT; goto out; }
            }
            i += (uint8_t)(2 + n);
            break;

        case OP_ICD_RX:
            NEED(2);
            n = ARG(1);
            ROOM(n);
            for (k = 0; k < n; k++) {
                if (icd_rx(&reply[reply_len], ARG(0))) { err = ERR_TIMEOUT; goto out; }
                reply_len++;
            }
            i += 2;
            break;

        default:
            err = ERR_UNKNOWN_OP;
            goto out;
        }
    }

out:
    if (err == ERR_OK && (power_status() & (ST_VDD_FAULT | ST_VPP_FAULT))) {
        err = ERR_POWER_FAULT;
        op_at = 0;
    }
    reply[0] = err;
    reply[1] = err ? op_at : 0;
}

static void fatal_to_bootloader(void)
{
    hw_init();
    enter_bootloader();
}

void main(void)
{
    uint8_t len;
    uint16_t led_timer = 0;

#if DEV_FAILSAFE
    if (!RCONbits.TO || STKPTRbits.STKFUL || STKPTRbits.STKUNF)
        fatal_to_bootloader();
#endif

    hw_init();
    power_init();
    icsp_set_speed(0);
    INTCONbits.PEIE = 1;
    INTCONbits.GIE = 1;
    WDTCONbits.SWDTEN = 1;      /* about 131 s with the configured postscaler */

    usb_init();
    LED = 1;

    for (;;) {
        CLRWDT();
        usb_poll();

        if (usb_boot_request) {
            delay_ms(50);       /* let the status stage finish */
            usb_poll();
            enter_bootloader();
        }

        if (!usb_configured()) {
#if DEV_FAILSAFE
            if (uptime_ms > ENUM_TIMEOUT_MS)
                enter_bootloader();
#endif
            /* Slow blink while waiting for the host. */
            LED = (uptime_ms & 0x200) ? 1 : 0;
            continue;
        }

        len = usb_rx_len();
        if (len != 0xFF) {
            process(len);
            usb_tx(reply, reply_len);
            usb_rx_release();
            if (deferred == OP_BOOTLOADER) {
                delay_ms(50);
                usb_poll();
                enter_bootloader();
            } else if (deferred == OP_RESET) {
                delay_ms(50);
                usb_poll();
                target_safe();
                UCON = 0;
                delay_ms(300);
                RESET();
            }
        }

        /* Fast blink while a power fault is latched, otherwise steady. */
        if (power_status() & (ST_VDD_FAULT | ST_VPP_FAULT)) {
            if (++led_timer == 0x4000) {
                led_timer = 0;
                LED ^= 1;
            }
        }
    }
}

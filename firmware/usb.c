/*
 * Minimal polled USB device stack for the PIC18F2550.
 */
#include <xc.h>
#include <string.h>
#include "usb.h"

/* Buffer descriptor status bits */
#define BD_UOWN    0x80
#define BD_DTS     0x40
#define BD_DTSEN   0x08
#define BD_BSTALL  0x04
#define BD_PID(s)  (((s) >> 2) & 0x0F)
#define PID_SETUP  0x0D

typedef struct {
    uint8_t stat;
    uint8_t cnt;
    uint8_t adrl;
    uint8_t adrh;
} bd_t;

/* Buffer descriptor table and endpoint buffers, all in USB dual-port RAM. */
#define BDT_ADDR      0x400
#define EP0_OUT_ADDR  0x410
#define EP0_IN_ADDR   0x450
#define EP1_OUT_ADDR  0x490
#define EP1_IN_ADDR   0x4D0

static volatile bd_t    bdt[4]                __at(BDT_ADDR);
static volatile uint8_t ep0_out[USB_PKT_SIZE] __at(EP0_OUT_ADDR);
static volatile uint8_t ep0_in[USB_PKT_SIZE]  __at(EP0_IN_ADDR);
volatile uint8_t usb_rx_buf[USB_PKT_SIZE]     __at(EP1_OUT_ADDR);
static volatile uint8_t ep1_in[USB_PKT_SIZE]  __at(EP1_IN_ADDR);

#define BD_EP0_OUT 0
#define BD_EP0_IN  1
#define BD_EP1_OUT 2
#define BD_EP1_IN  3

static const uint8_t device_desc[] = {
    18, 1,                      /* bLength, DEVICE */
    0x00, 0x02,                 /* bcdUSB 2.00 */
    0x00, 0x00, 0x00,           /* class, subclass, protocol: per interface */
    USB_PKT_SIZE,               /* bMaxPacketSize0 */
    USB_VID & 0xFF, USB_VID >> 8,
    USB_PID & 0xFF, USB_PID >> 8,
    USB_BCD_DEVICE & 0xFF, USB_BCD_DEVICE >> 8,
    1, 2, 0,                    /* iManufacturer, iProduct, iSerialNumber */
    1                           /* bNumConfigurations */
};

static const uint8_t config_desc[] = {
    9, 2,                       /* bLength, CONFIGURATION */
    32, 0,                      /* wTotalLength */
    1, 1, 0,                    /* bNumInterfaces, bConfigurationValue, iConfiguration */
    0x80, 50,                   /* bus powered, 100 mA */

    9, 4,                       /* bLength, INTERFACE */
    0, 0, 2,                    /* bInterfaceNumber, bAlternateSetting, bNumEndpoints */
    0xFF, 0x00, 0x00,           /* vendor specific */
    0,

    7, 5, 0x01, 0x02, USB_PKT_SIZE, 0, 0,     /* EP1 OUT, bulk */
    7, 5, 0x81, 0x02, USB_PKT_SIZE, 0, 0      /* EP1 IN, bulk */
};

static const uint8_t string0[] = { 4, 3, 0x09, 0x04 };
static const char manufacturer[] = "pic16f1-toolchain";
static const char product[] = "PICkit 2 ICSP probe";

static uint8_t configured;
static uint8_t pending_addr;
static uint8_t out_toggle, in_toggle;
static uint8_t rx_len = 0xFF;
volatile uint8_t usb_boot_request;

static void arm_ep0_out(void)
{
    bdt[BD_EP0_OUT].cnt = USB_PKT_SIZE;
    bdt[BD_EP0_OUT].adrl = EP0_OUT_ADDR & 0xFF;
    bdt[BD_EP0_OUT].adrh = EP0_OUT_ADDR >> 8;
    bdt[BD_EP0_OUT].stat = BD_UOWN;
}

static void arm_ep1_out(void)
{
    bdt[BD_EP1_OUT].cnt = USB_PKT_SIZE;
    bdt[BD_EP1_OUT].adrl = EP1_OUT_ADDR & 0xFF;
    bdt[BD_EP1_OUT].adrh = EP1_OUT_ADDR >> 8;
    bdt[BD_EP1_OUT].stat = out_toggle ? (BD_UOWN | BD_DTS | BD_DTSEN)
                                      : (BD_UOWN | BD_DTSEN);
}

static void set_configuration(uint8_t value)
{
    UEP1 = 0;
    bdt[BD_EP1_OUT].stat = 0;
    bdt[BD_EP1_IN].stat = 0;
    out_toggle = 0;
    in_toggle = 0;
    rx_len = 0xFF;
    configured = value;
    if (value) {
        bdt[BD_EP1_IN].adrl = EP1_IN_ADDR & 0xFF;
        bdt[BD_EP1_IN].adrh = EP1_IN_ADDR >> 8;
        arm_ep1_out();
        UEP1 = 0x1E;            /* handshake, no control, OUT and IN */
    }
}

static void bus_reset(void)
{
    UEIR = 0;
    UIR = 0;
    UADDR = 0;
    UEP1 = 0;
    UEP0 = 0x16;                /* handshake, control, OUT and IN */
    while (UIRbits.TRNIF)
        UIRbits.TRNIF = 0;
    UCONbits.PPBRST = 1;
    UCONbits.PPBRST = 0;
    UCONbits.PKTDIS = 0;
    pending_addr = 0;
    set_configuration(0);
    bdt[BD_EP0_IN].stat = 0;
    bdt[BD_EP0_IN].adrl = EP0_IN_ADDR & 0xFF;
    bdt[BD_EP0_IN].adrh = EP0_IN_ADDR >> 8;
    arm_ep0_out();
}

static uint8_t string_desc(const char *s)
{
    uint8_t n = 2;

    while (*s && n < USB_PKT_SIZE - 1) {
        ep0_in[n++] = (uint8_t)*s++;
        ep0_in[n++] = 0;
    }
    ep0_in[0] = n;
    ep0_in[1] = 3;
    return n;
}

static void copy_desc(const uint8_t *d, uint8_t n)
{
    uint8_t i;

    for (i = 0; i < n; i++)
        ep0_in[i] = d[i];
}

#define NO_REPLY 0xFF

static void setup_packet(void)
{
    uint8_t type   = ep0_out[0];
    uint8_t req    = ep0_out[1];
    uint8_t val_l  = ep0_out[2];
    uint8_t val_h  = ep0_out[3];
    uint8_t len_l  = ep0_out[6];
    uint8_t len_h  = ep0_out[7];
    uint8_t n = NO_REPLY;

    bdt[BD_EP0_IN].stat = 0;    /* cancel anything still queued */

    if ((type & 0x60) == 0x00) {
        switch (req) {
        case 0:                 /* GET_STATUS */
            ep0_in[0] = 0;
            ep0_in[1] = 0;
            n = 2;
            break;
        case 1:                 /* CLEAR_FEATURE */
        case 3:                 /* SET_FEATURE */
            if ((type & 0x1F) == 2 && configured)
                set_configuration(configured);      /* resets the toggles */
            n = 0;
            break;
        case 5:                 /* SET_ADDRESS */
            pending_addr = val_l | 0x80;
            n = 0;
            break;
        case 6:                 /* GET_DESCRIPTOR */
            if (val_h == 1) {
                n = sizeof device_desc;
                copy_desc(device_desc, n);
            } else if (val_h == 2) {
                n = sizeof config_desc;
                copy_desc(config_desc, n);
            } else if (val_h == 3) {
                if (val_l == 0) {
                    n = sizeof string0;
                    copy_desc(string0, n);
                } else if (val_l == 1) {
                    n = string_desc(manufacturer);
                } else if (val_l == 2) {
                    n = string_desc(product);
                }
            }
            break;
        case 8:                 /* GET_CONFIGURATION */
            ep0_in[0] = configured;
            n = 1;
            break;
        case 9:                 /* SET_CONFIGURATION */
            if (val_l <= 1) {
                set_configuration(val_l);
                n = 0;
            }
            break;
        case 10:                /* GET_INTERFACE */
            ep0_in[0] = 0;
            n = 1;
            break;
        case 11:                /* SET_INTERFACE */
            n = 0;
            break;
        default:
            break;
        }
    } else if ((type & 0x60) == 0x40) {
        if (req == USB_REQ_BOOTLOADER && type == 0x40 &&
            val_l == (USB_BOOT_MAGIC & 0xFF) && val_h == (USB_BOOT_MAGIC >> 8)) {
            usb_boot_request = 1;
            n = 0;
        } else if (req == USB_REQ_INFO && type == 0xC0) {
            n = app_info((uint8_t *)ep0_in);
        }
    }

    if (n == NO_REPLY) {
        bdt[BD_EP0_OUT].cnt = USB_PKT_SIZE;
        bdt[BD_EP0_OUT].stat = BD_UOWN | BD_BSTALL;
        bdt[BD_EP0_IN].stat = BD_UOWN | BD_BSTALL;
    } else {
        if (type & 0x80) {
            if (len_h == 0 && len_l < n)
                n = len_l;
        } else {
            n = 0;
        }
        bdt[BD_EP0_IN].cnt = n;
        bdt[BD_EP0_IN].stat = BD_UOWN | BD_DTS | BD_DTSEN;
        arm_ep0_out();
    }
    UCONbits.PKTDIS = 0;
}

static void transaction(uint8_t ustat)
{
    switch (ustat & 0x7C) {
    case 0x00:                  /* EP0 OUT or SETUP */
        if (BD_PID(bdt[BD_EP0_OUT].stat) == PID_SETUP)
            setup_packet();
        else
            arm_ep0_out();
        break;
    case 0x04:                  /* EP0 IN */
        if (pending_addr) {
            UADDR = pending_addr & 0x7F;
            pending_addr = 0;
        }
        break;
    case 0x08:                  /* EP1 OUT */
        rx_len = bdt[BD_EP1_OUT].cnt;
        out_toggle ^= 1;
        break;
    default:                    /* EP1 IN: nothing to do */
        break;
    }
}

void usb_init(void)
{
    UCON = 0;
    UIE = 0;
    UEIE = 0;
    UCFG = 0x14;                /* internal pull-up, full speed, no ping-pong */
    configured = 0;
    usb_boot_request = 0;
    UCONbits.USBEN = 1;
    bus_reset();
}

void usb_poll(void)
{
    if (UIRbits.URSTIF) {
        bus_reset();
        return;
    }
    if (UIRbits.STALLIF) {
        if (UEP0bits.EPSTALL) {
            arm_ep0_out();
            UEP0bits.EPSTALL = 0;
        }
        UIRbits.STALLIF = 0;
    }
    if (UIRbits.UERRIF) {
        UEIR = 0;
        UIRbits.UERRIF = 0;
    }
    if (UIRbits.IDLEIF)
        UIRbits.IDLEIF = 0;
    if (UIRbits.ACTVIF)
        UIRbits.ACTVIF = 0;
    if (UIRbits.SOFIF)
        UIRbits.SOFIF = 0;

    while (UIRbits.TRNIF) {
        uint8_t ustat = USTAT;

        UIRbits.TRNIF = 0;
        transaction(ustat);
    }
}

uint8_t usb_configured(void)
{
    return configured;
}

uint8_t usb_rx_len(void)
{
    return rx_len;
}

void usb_rx_release(void)
{
    rx_len = 0xFF;
    if (configured)
        arm_ep1_out();
}

void usb_tx(const uint8_t *data, uint8_t len)
{
    uint8_t i;

    while (bdt[BD_EP1_IN].stat & BD_UOWN) {
        CLRWDT();
        usb_poll();
        if (!configured)
            return;
    }
    for (i = 0; i < len; i++)
        ep1_in[i] = data[i];
    bdt[BD_EP1_IN].cnt = len;
    bdt[BD_EP1_IN].stat = in_toggle ? (BD_UOWN | BD_DTS | BD_DTSEN)
                                    : (BD_UOWN | BD_DTSEN);
    in_toggle ^= 1;
}

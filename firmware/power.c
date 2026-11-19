/*
 * Target power: VDD regulator, VPP boost converter, MCLR drive.
 *
 * VDD   CCP1 produces a filtered reference for the VDD regulator.
 *       duty(10 bit, PR2 = 79) = Vdd * 32 + 10.5
 * VPP   CCP2 drives the boost converter switch.  Regulation is hysteretic:
 *       Timer1 starts a conversion of the VPP feedback every 125 us and the
 *       conversion interrupt turns the PWM duty on or off around the
 *       setpoint.  The same loop watches VDD and VPP for a short circuit.
 *
 * The scaling and calibration constants match the factory calibration that
 * the PICkit 2 keeps in the first four bytes of its data EEPROM.
 */
#include "hw.h"

#define PWM_PERIOD        79      /* 150 kHz at 48 MHz */
#define VPP_DUTY_ON       64      /* CCPR2L while pumping (80 %) */
#define ADC_VDD           0x05    /* ADCON0: channel 1, ADC on */
#define ADC_VPP           0x01    /* ADCON0: channel 0, ADC on */
#define TMR1_RELOAD_H     0xFA    /* 65536 - 1500 = 125 us */
#define TMR1_RELOAD_L     0x24
#define FAULT_SAMPLES     12

static volatile uint8_t  vpp_upper, vpp_lower;    /* 8 bit ADC limits */
static volatile uint8_t  vdd_fault_level, vpp_fault_level;
static volatile uint8_t  vdd_fault_count, vpp_fault_count;
static volatile uint8_t  faults;
static volatile uint8_t  pump_hold;
static volatile uint16_t raw_vdd, raw_vpp;        /* left justified results */
static volatile uint8_t  tick_div;
volatile uint16_t uptime_ms;

static uint16_t adc_cal;      /* 0x100 = unity */
static int8_t   vdd_offset;
static uint8_t  vdd_cal;      /* 0x80 = unity */

static uint16_t vdd_setpoint_mv = 3300;

uint8_t ee_read(uint8_t addr)
{
    EEADR = addr;
    EECON1 = 0;
    EECON1bits.RD = 1;
    return EEDATA;
}

void ee_write(uint8_t addr, uint8_t value)
{
    EEADR = addr;
    EEDATA = value;
    EECON1 = 0x04;              /* data EEPROM, write enable */
    INTCONbits.GIE = 0;
    EECON2 = 0x55;
    EECON2 = 0xAA;
    EECON1bits.WR = 1;
    INTCONbits.GIE = 1;
    while (EECON1bits.WR)
        CLRWDT();
    EECON1 = 0;
}

/* Calibration factors, in the format the stock PICkit 2 firmware stores. */
void power_load_cal(void)
{
    adc_cal    = (uint16_t)ee_read(0) | ((uint16_t)ee_read(1) << 8);
    vdd_offset = (int8_t)ee_read(2);
    vdd_cal    = ee_read(3);
    if (adc_cal > 0x140 || adc_cal < 0xC0 || vdd_cal > 0xAF || vdd_cal < 0x50) {
        adc_cal = 0x100;
        vdd_offset = 0;
        vdd_cal = 0x80;
    }
    power_set_vdd(vdd_setpoint_mv);
}

/* Scale an ideal 8 bit ADC threshold to what this unit's ADC will read. */
static uint8_t cal_threshold(uint8_t ideal)
{
    uint16_t inv = (uint16_t)(0x200u - adc_cal);
    return (uint8_t)(((uint32_t)inv * ideal) >> 8);
}

void power_isr(void)
{
    /* The VPP conversion comes first: if both interrupts are pending (they
     * can be after interrupts were masked for the debug link) the result
     * register holds a VPP sample, not a VDD sample. */
    if (PIR1bits.ADIF && PIE1bits.ADIE) {
        uint8_t v = ADRESH;

        PIR1bits.ADIF = 0;
        raw_vpp = ((uint16_t)v << 8) | ADRESL;

        if (CCP2CON) {
            if (pump_hold || v > vpp_upper)
                CCPR2L = 0;
            else if (v < vpp_lower)
                CCPR2L = VPP_DUTY_ON;

            if (VPP_SWITCH && v < vpp_fault_level) {
                if (vpp_fault_count == FAULT_SAMPLES) {
                    VPP_SWITCH = 0;
                    VDD_OFF_N = 1;
                    faults |= ST_VPP_FAULT;
                } else {
                    vpp_fault_count++;
                }
            } else {
                vpp_fault_count = 0;
            }
        }

        ADCON0 = ADC_VDD;
        PIE1bits.ADIE = 0;
        ADCON0bits.GO = 1;
    }

    if (PIR1bits.TMR1IF) {
        PIR1bits.TMR1IF = 0;
        TMR1H = TMR1_RELOAD_H;
        TMR1L = TMR1_RELOAD_L;

        if (++tick_div == 8) {
            tick_div = 0;
            uptime_ms++;
        }

        /* Act only on a finished VDD conversion; otherwise wait a tick. */
        if (ADCON0 == ADC_VDD) {
            raw_vdd = ((uint16_t)ADRESH << 8) | ADRESL;
            if (!VDD_OFF_N && ADRESH < vdd_fault_level) {
                if (vdd_fault_count == FAULT_SAMPLES) {
                    VPP_SWITCH = 0;
                    VDD_OFF_N = 1;
                    faults |= ST_VDD_FAULT;
                } else {
                    vdd_fault_count++;
                }
            } else {
                vdd_fault_count = 0;
            }

            PIR1bits.ADIF = 0;
            ADCON0 = ADC_VPP;
            PIE1bits.ADIE = 1;
            ADCON0bits.GO = 1;
        }
    }
}

void power_init(void)
{
    /* Timer2 is the PWM time base for both CCP modules. */
    PR2 = PWM_PERIOD;
    T2CON = 0x04;
    CCP1CON = 0x0C;
    CCP2CON = 0x00;
    CCPR2L = 0;
    power_load_cal();

    vpp_upper = 0;
    vpp_lower = 0;
    vpp_fault_level = 0;

    ADCON1 = 0x0D;            /* AN0 and AN1 analog, references VDD/VSS */
    ADCON2 = 0x26;            /* left justified, 8 Tad, Fosc/64 */
    ADCON0 = ADC_VDD;

    T1CON = 0x80;             /* 16 bit access, Fosc/4, 1:1 */
    TMR1H = TMR1_RELOAD_H;
    TMR1L = TMR1_RELOAD_L;
    PIR1bits.TMR1IF = 0;
    PIE1bits.ADIE = 0;
    PIE1bits.TMR1IE = 1;
    T1CONbits.TMR1ON = 1;
    ADCON0bits.GO = 1;
}

uint8_t power_set_vdd(uint16_t mv)
{
    int32_t d;

    if (mv < VDD_MIN_MV || mv > VDD_MAX_MV)
        return 1;
    vdd_setpoint_mv = mv;

    d = ((int32_t)mv * 32 + 10500) / 1000;
    d = ((d + vdd_offset) * vdd_cal) >> 7;
    if (d < 0)
        d = 0;
    if (d > 4 * (PWM_PERIOD + 1))
        d = 4 * (PWM_PERIOD + 1);

    CCPR1L = (uint8_t)(d >> 2);
    CCP1CON = (uint8_t)(0x0C | ((d & 3) << 4));

    /* Fault when VDD sits below 70 % of the setpoint: 255 counts = 5 V. */
    vdd_fault_level = cal_threshold((uint8_t)(((uint32_t)mv * 36) / 1000));
    return 0;
}

void power_vdd_mode(uint8_t mode)
{
    vdd_fault_count = 0;
    switch (mode) {
    case 1:
        VDD_GND = 0;          /* never both half-bridge gates at once */
        VDD_OFF_N = 0;
        break;
    case 2:
        VDD_OFF_N = 1;
        VDD_GND = 1;
        break;
    default:
        VDD_OFF_N = 1;
        VDD_GND = 0;
        break;
    }
}

uint8_t power_set_vpp(uint16_t mv)
{
    uint8_t t;

    if (mv > VPP_MAX_MV || (mv != 0 && mv < VPP_MIN_MV))
        return 1;

    if (mv == 0) {
        CCP2CON = 0;
        LATCbits.LATC1 = 0;
        CCPR2L = 0;
        return 0;
    }

    /* 18.61 counts per volt on the 8 bit result. */
    t = cal_threshold((uint8_t)(((uint32_t)mv * 4878u) >> 18));
    PIE1bits.TMR1IE = 0;
    vpp_upper = t + 1;
    vpp_lower = t - 1;
    vpp_fault_level = (uint8_t)(((uint16_t)t * 179u) >> 8);   /* 70 % */
    vpp_fault_count = 0;
    PIE1bits.TMR1IE = 1;
    CCP2CON = 0x0C;
    return 0;
}

void power_mclr(uint8_t mode)
{
    vpp_fault_count = 0;
    switch (mode) {
    case 1:
        VPP_SWITCH = 0;
        MCLR_GND = 1;
        break;
    case 2:
        MCLR_GND = 0;
        VPP_SWITCH = 1;
        break;
    default:
        VPP_SWITCH = 0;
        MCLR_GND = 0;
        break;
    }
}

uint8_t power_status(void)
{
    uint8_t s = faults;

    if (!VDD_OFF_N)   s |= ST_VDD_ON;
    if (VDD_GND)      s |= ST_VDD_GND;
    if (CCP2CON)      s |= ST_VPP_PUMP;
    if (VPP_SWITCH)   s |= ST_VPP_SWITCH;
    if (MCLR_GND)     s |= ST_MCLR_GND;
    if (!BUTTON_IN)   s |= ST_BUTTON;
    return s;
}

void power_clear_faults(void)
{
    faults = 0;
}

void power_read_raw(uint16_t *vdd, uint16_t *vpp)
{
    INTCONbits.GIE = 0;
    *vdd = raw_vdd >> 6;
    *vpp = raw_vpp >> 6;
    INTCONbits.GIE = 1;
}

uint16_t power_read_vdd_mv(void)
{
    uint16_t vdd, vpp;

    power_read_raw(&vdd, &vpp);
    vdd = (uint16_t)(((uint32_t)vdd * adc_cal) >> 8);
    return (uint16_t)(((uint32_t)vdd * 5005u) >> 10);     /* 5000 / 1023 */
}

uint16_t power_read_vpp_mv(void)
{
    uint16_t vdd, vpp;

    power_read_raw(&vdd, &vpp);
    vpp = (uint16_t)(((uint32_t)vpp * adc_cal) >> 8);
    return (uint16_t)(((uint32_t)vpp * 13756u) >> 10);    /* 1000 / 74.44 */
}

/*
 * While interrupts are masked the regulator cannot run, so the pump must not
 * be left switching open loop.
 */
void power_pump_pause(void)
{
    pump_hold = 1;
    CCPR2L = 0;
}

void power_pump_resume(void)
{
    pump_hold = 0;
}

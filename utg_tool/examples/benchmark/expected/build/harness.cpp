#include "CppUTest/CommandLineTestRunner.h"
#include "CppUTest/TestHarness.h"
#include "CppUTestExt/MockSupport.h"
extern "C" {
#include "/home/claude/utg_tool/examples/benchmark/src/bsw/pal/types.h"
#include "/home/claude/utg_tool/examples/benchmark/prelude.h"
#include "/home/claude/utg_tool/examples/benchmark/test/mock/lsout11/source.h"
#include "/home/claude/utg_tool/examples/benchmark/test/mock/lsout11/source.c"
}

/* accessor pointers (convention from the project configuration) */
static F32 * const p_f32_CuLSOut11 = &f32_CuLSOut11;
static F32 * const p_f32_LSOut11Short = &f32_LSOut11Short;
static U8 * const p_u8_time_LSOut11Short = &u8_time_LSOut11Short;
static U8 * const p_u8_MaxTime_LSOut11Short = &u8_MaxTime_LSOut11Short;
static F32 * const p_f32_CuLSOut11Short = &f32_CuLSOut11Short;
static F32 * const p_f32_LSOut11CurrH = &f32_LSOut11CurrH;
static U8 * const p_u8_time_LSOut11CurrH = &u8_time_LSOut11CurrH;
static U8 * const p_u8_MaxTime_LSOut11CurrH = &u8_MaxTime_LSOut11CurrH;
static F32 * const p_f32_CuLSOut11CurrH = &f32_CuLSOut11CurrH;
static BO * const p_b_LSOut11_10ms = &b_LSOut11_10ms;

/* mock implementations derived from the declarations */
volt_ratio_physical_t sig_hwc_rx_cu_meas_11_get(void)
{
    return *static_cast<volt_ratio_physical_t*>(mock().actualCall("sig_hwc_rx_cu_meas_11_get").returnPointerValue());
}

VO sig_hwc_tx_LS11_set(BO b_LSOut11_250us)
{
    mock().actualCall("sig_hwc_tx_LS11_set").withParameter("b_LSOut11_250us", (int)b_LSOut11_250us);
}

VO sig_hwc_tx_LS11_flush(void)
{
    mock().actualCall("sig_hwc_tx_LS11_flush");
}

#include "/home/claude/utg_tool/examples/benchmark/expected/build/test_rc_lsout11_out_250us.cpp"

int main(int argc, char** argv)
{
    return CommandLineTestRunner::RunAllTests(argc, argv);
}

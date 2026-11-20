/**
 * \file  test_rc_lsout11_out_250us.cpp
 * \brief Unit tests for rc_lsout11_out_250us().
 * \author Subhasish Singha <subhasish.singha1@kiongroup.com>
 *
 * Strategies : branch, condition, boundary
 * Scenarios  : 12
 */
#include "CppUTest/TestHarness.h"
#include "CppUTestExt/MockSupport.h"

TEST_GROUP(rc_lsout11_out_250us)
{
    void setup()
    {
        mock().clear();
    }

    void teardown()
    {
        mock().clear();
    }
};

/**
 * \brief Target: C1 decision TRUE: f32_LSOut11Short <= f32_CuLSOut11. Decisions taken: C1=TRUE, C2=TRUE,
 * C3=TRUE, C4=TRUE, C5=FALSE, C6=TRUE.
 *
 * \test
 * \pre Inputs: f32_CuLSOut11 = 1.0f; f32_LSOut11Short = 0.0f; u8_time_LSOut11Short = 0; u8_MaxTime_LSOut11Short
 * \pre   = 0; f32_CuLSOut11Short = 0.0f; f32_LSOut11CurrH = 0.0f; u8_time_LSOut11CurrH = 0;
 * \pre   u8_MaxTime_LSOut11CurrH = 0; f32_CuLSOut11CurrH = 0.0f; b_LSOut11_10ms = TRUE.
 * \pre Mocks (in call order): sig_hwc_rx_cu_meas_11_get(returns .physical = 0.0f);
 * \pre   sig_hwc_tx_LS11_set(b_LSOut11_250us = TRUE); sig_hwc_tx_LS11_flush().
 * \post Return value RC_SUCCESS; f32_CuLSOut11 == 0.0f; u8_time_LSOut11Short == 1; f32_CuLSOut11Short == 0.0f;
 * \post   u8_time_LSOut11CurrH == 1; f32_CuLSOut11CurrH == 0.0f.
 */
TEST(rc_lsout11_out_250us, Testcase_1_1)
{
    /* Initialize input variables */
    *p_f32_CuLSOut11 = 1.0f;
    *p_f32_LSOut11Short = 0.0f;
    *p_u8_time_LSOut11Short = 0;
    *p_u8_MaxTime_LSOut11Short = 0;
    *p_f32_CuLSOut11Short = 0.0f;
    *p_f32_LSOut11CurrH = 0.0f;
    *p_u8_time_LSOut11CurrH = 0;
    *p_u8_MaxTime_LSOut11CurrH = 0;
    *p_f32_CuLSOut11CurrH = 0.0f;
    *p_b_LSOut11_10ms = TRUE;

    /* Configure mock expectations */
    volt_ratio_physical_t sig_hwc_rx_cu_meas_11_get_ret = {0.0f};

    mock().strictOrder();
    mock().expectOneCall("sig_hwc_rx_cu_meas_11_get")
          .andReturnValue(&sig_hwc_rx_cu_meas_11_get_ret);
    mock().expectOneCall("sig_hwc_tx_LS11_set")
          .withParameter("b_LSOut11_250us", (int)TRUE);
    mock().expectOneCall("sig_hwc_tx_LS11_flush");

    /* Execute the function */
    RC ret = rc_lsout11_out_250us();

    /* Check return value */
    CHECK_EQUAL(RC_SUCCESS, ret);

    /* Check modified variables */
    DOUBLES_EQUAL(0.0f, *p_f32_CuLSOut11, 0.0001);
    CHECK_EQUAL(1, *p_u8_time_LSOut11Short);
    DOUBLES_EQUAL(0.0f, *p_f32_CuLSOut11Short, 0.0001);
    CHECK_EQUAL(1, *p_u8_time_LSOut11CurrH);
    DOUBLES_EQUAL(0.0f, *p_f32_CuLSOut11CurrH, 0.0001);

    /* Check mock expectations */
    mock().checkExpectations();
}

/**
 * \brief Target: C1 decision FALSE: f32_LSOut11Short <= f32_CuLSOut11. Decisions taken: C1=FALSE, C2=FALSE,
 * C3=FALSE, C4=FALSE, C5=FALSE, C6=FALSE.
 *
 * \test
 * \pre Inputs: f32_CuLSOut11 = 0.0f; f32_LSOut11Short = 0.0f; u8_time_LSOut11Short = 1; u8_MaxTime_LSOut11Short
 * \pre   = 1; f32_CuLSOut11Short = 0.0f; f32_LSOut11CurrH = 0.0f; u8_time_LSOut11CurrH = 1;
 * \pre   u8_MaxTime_LSOut11CurrH = 1; f32_CuLSOut11CurrH = 0.0f; b_LSOut11_10ms = FALSE.
 * \pre Mocks (in call order): sig_hwc_rx_cu_meas_11_get(returns .physical = -1.0f);
 * \pre   sig_hwc_tx_LS11_set(b_LSOut11_250us = FALSE); sig_hwc_tx_LS11_flush().
 * \post Return value RC_SUCCESS; f32_CuLSOut11 == -1.0f; u8_time_LSOut11Short == 0; u8_time_LSOut11CurrH == 0.
 */
TEST(rc_lsout11_out_250us, Testcase_1_2)
{
    /* Initialize input variables */
    *p_f32_CuLSOut11 = 0.0f;
    *p_f32_LSOut11Short = 0.0f;
    *p_u8_time_LSOut11Short = 1;
    *p_u8_MaxTime_LSOut11Short = 1;
    *p_f32_CuLSOut11Short = 0.0f;
    *p_f32_LSOut11CurrH = 0.0f;
    *p_u8_time_LSOut11CurrH = 1;
    *p_u8_MaxTime_LSOut11CurrH = 1;
    *p_f32_CuLSOut11CurrH = 0.0f;
    *p_b_LSOut11_10ms = FALSE;

    /* Configure mock expectations */
    volt_ratio_physical_t sig_hwc_rx_cu_meas_11_get_ret = {-1.0f};

    mock().strictOrder();
    mock().expectOneCall("sig_hwc_rx_cu_meas_11_get")
          .andReturnValue(&sig_hwc_rx_cu_meas_11_get_ret);
    mock().expectOneCall("sig_hwc_tx_LS11_set")
          .withParameter("b_LSOut11_250us", (int)FALSE);
    mock().expectOneCall("sig_hwc_tx_LS11_flush");

    /* Execute the function */
    RC ret = rc_lsout11_out_250us();

    /* Check return value */
    CHECK_EQUAL(RC_SUCCESS, ret);

    /* Check modified variables */
    DOUBLES_EQUAL(-1.0f, *p_f32_CuLSOut11, 0.0001);
    CHECK_EQUAL(0, *p_u8_time_LSOut11Short);
    CHECK_EQUAL(0, *p_u8_time_LSOut11CurrH);

    /* Check mock expectations */
    mock().checkExpectations();
}

/**
 * \brief Target: C2.a1 [u8_MaxTime_LSOut11Short <= u8_time_LSOut11Short]: lhs equal to rhs after C1=TRUE.
 * Decisions taken: C1=TRUE, C2=TRUE, C3=TRUE, C4=TRUE, C5=TRUE.
 *
 * \test
 * \pre Inputs: f32_CuLSOut11 = 0.0f; f32_LSOut11Short = 0.0f; u8_time_LSOut11Short = 0; u8_MaxTime_LSOut11Short
 * \pre   = 1; f32_CuLSOut11Short = 0.0f; f32_LSOut11CurrH = 0.0f; u8_time_LSOut11CurrH = 0;
 * \pre   u8_MaxTime_LSOut11CurrH = 0; f32_CuLSOut11CurrH = 0.0f.
 * \pre Mocks (in call order): sig_hwc_rx_cu_meas_11_get(returns .physical = 1.0f);
 * \pre   sig_hwc_tx_LS11_set(b_LSOut11_250us = FALSE); sig_hwc_tx_LS11_flush().
 * \post Return value RC_SUCCESS; f32_CuLSOut11 == 1.0f; u8_time_LSOut11Short == 1; f32_CuLSOut11Short == 1.0f;
 * \post   u8_time_LSOut11CurrH == 1; f32_CuLSOut11CurrH == 1.0f.
 */
TEST(rc_lsout11_out_250us, Testcase_1_3)
{
    /* Initialize input variables */
    *p_f32_CuLSOut11 = 0.0f;
    *p_f32_LSOut11Short = 0.0f;
    *p_u8_time_LSOut11Short = 0;
    *p_u8_MaxTime_LSOut11Short = 1;
    *p_f32_CuLSOut11Short = 0.0f;
    *p_f32_LSOut11CurrH = 0.0f;
    *p_u8_time_LSOut11CurrH = 0;
    *p_u8_MaxTime_LSOut11CurrH = 0;
    *p_f32_CuLSOut11CurrH = 0.0f;

    /* Configure mock expectations */
    volt_ratio_physical_t sig_hwc_rx_cu_meas_11_get_ret = {1.0f};

    mock().strictOrder();
    mock().expectOneCall("sig_hwc_rx_cu_meas_11_get")
          .andReturnValue(&sig_hwc_rx_cu_meas_11_get_ret);
    mock().expectOneCall("sig_hwc_tx_LS11_set")
          .withParameter("b_LSOut11_250us", (int)FALSE);
    mock().expectOneCall("sig_hwc_tx_LS11_flush");

    /* Execute the function */
    RC ret = rc_lsout11_out_250us();

    /* Check return value */
    CHECK_EQUAL(RC_SUCCESS, ret);

    /* Check modified variables */
    DOUBLES_EQUAL(1.0f, *p_f32_CuLSOut11, 0.0001);
    CHECK_EQUAL(1, *p_u8_time_LSOut11Short);
    DOUBLES_EQUAL(1.0f, *p_f32_CuLSOut11Short, 0.0001);
    CHECK_EQUAL(1, *p_u8_time_LSOut11CurrH);
    DOUBLES_EQUAL(1.0f, *p_f32_CuLSOut11CurrH, 0.0001);

    /* Check mock expectations */
    mock().checkExpectations();
}

/**
 * \brief Target: C2.a1 [u8_MaxTime_LSOut11Short <= u8_time_LSOut11Short]: lhs greater than rhs after C1=TRUE.
 * Decisions taken: C1=TRUE, C2=FALSE, C3=TRUE, C4=TRUE, C5=TRUE.
 *
 * \test
 * \pre Inputs: f32_CuLSOut11 = 0.0f; f32_LSOut11Short = 0.0f; u8_time_LSOut11Short = 0; u8_MaxTime_LSOut11Short
 * \pre   = 2; f32_CuLSOut11Short = 0.0f; f32_LSOut11CurrH = 0.0f; u8_time_LSOut11CurrH = 0;
 * \pre   u8_MaxTime_LSOut11CurrH = 0; f32_CuLSOut11CurrH = 0.0f.
 * \pre Mocks (in call order): sig_hwc_rx_cu_meas_11_get(returns .physical = 1.0f);
 * \pre   sig_hwc_tx_LS11_set(b_LSOut11_250us = FALSE); sig_hwc_tx_LS11_flush().
 * \post Return value RC_SUCCESS; f32_CuLSOut11 == 1.0f; u8_time_LSOut11Short == 1; u8_time_LSOut11CurrH == 1;
 * \post   f32_CuLSOut11CurrH == 1.0f.
 */
TEST(rc_lsout11_out_250us, Testcase_1_4)
{
    /* Initialize input variables */
    *p_f32_CuLSOut11 = 0.0f;
    *p_f32_LSOut11Short = 0.0f;
    *p_u8_time_LSOut11Short = 0;
    *p_u8_MaxTime_LSOut11Short = 2;
    *p_f32_CuLSOut11Short = 0.0f;
    *p_f32_LSOut11CurrH = 0.0f;
    *p_u8_time_LSOut11CurrH = 0;
    *p_u8_MaxTime_LSOut11CurrH = 0;
    *p_f32_CuLSOut11CurrH = 0.0f;

    /* Configure mock expectations */
    volt_ratio_physical_t sig_hwc_rx_cu_meas_11_get_ret = {1.0f};

    mock().strictOrder();
    mock().expectOneCall("sig_hwc_rx_cu_meas_11_get")
          .andReturnValue(&sig_hwc_rx_cu_meas_11_get_ret);
    mock().expectOneCall("sig_hwc_tx_LS11_set")
          .withParameter("b_LSOut11_250us", (int)FALSE);
    mock().expectOneCall("sig_hwc_tx_LS11_flush");

    /* Execute the function */
    RC ret = rc_lsout11_out_250us();

    /* Check return value */
    CHECK_EQUAL(RC_SUCCESS, ret);

    /* Check modified variables */
    DOUBLES_EQUAL(1.0f, *p_f32_CuLSOut11, 0.0001);
    CHECK_EQUAL(1, *p_u8_time_LSOut11Short);
    CHECK_EQUAL(1, *p_u8_time_LSOut11CurrH);
    DOUBLES_EQUAL(1.0f, *p_f32_CuLSOut11CurrH, 0.0001);

    /* Check mock expectations */
    mock().checkExpectations();
}

/**
 * \brief Target: C2.a1 [u8_MaxTime_LSOut11Short <= u8_time_LSOut11Short]: lhs equal to rhs after C1=FALSE.
 * Decisions taken: C1=FALSE, C2=TRUE, C3=TRUE, C4=TRUE, C5=TRUE.
 *
 * \test
 * \pre Inputs: f32_CuLSOut11 = 0.0f; f32_LSOut11Short = 1.0f; u8_time_LSOut11Short = 1; u8_MaxTime_LSOut11Short
 * \pre   = 0; f32_CuLSOut11Short = 0.0f; f32_LSOut11CurrH = 0.0f; u8_time_LSOut11CurrH = 0;
 * \pre   u8_MaxTime_LSOut11CurrH = 0; f32_CuLSOut11CurrH = 0.0f.
 * \pre Mocks (in call order): sig_hwc_rx_cu_meas_11_get(returns .physical = 0.5f);
 * \pre   sig_hwc_tx_LS11_set(b_LSOut11_250us = FALSE); sig_hwc_tx_LS11_flush().
 * \post Return value RC_SUCCESS; f32_CuLSOut11 == 0.5f; u8_time_LSOut11Short == 0; f32_CuLSOut11Short == 0.5f;
 * \post   u8_time_LSOut11CurrH == 1; f32_CuLSOut11CurrH == 0.5f.
 */
TEST(rc_lsout11_out_250us, Testcase_1_5)
{
    /* Initialize input variables */
    *p_f32_CuLSOut11 = 0.0f;
    *p_f32_LSOut11Short = 1.0f;
    *p_u8_time_LSOut11Short = 1;
    *p_u8_MaxTime_LSOut11Short = 0;
    *p_f32_CuLSOut11Short = 0.0f;
    *p_f32_LSOut11CurrH = 0.0f;
    *p_u8_time_LSOut11CurrH = 0;
    *p_u8_MaxTime_LSOut11CurrH = 0;
    *p_f32_CuLSOut11CurrH = 0.0f;

    /* Configure mock expectations */
    volt_ratio_physical_t sig_hwc_rx_cu_meas_11_get_ret = {0.5f};

    mock().strictOrder();
    mock().expectOneCall("sig_hwc_rx_cu_meas_11_get")
          .andReturnValue(&sig_hwc_rx_cu_meas_11_get_ret);
    mock().expectOneCall("sig_hwc_tx_LS11_set")
          .withParameter("b_LSOut11_250us", (int)FALSE);
    mock().expectOneCall("sig_hwc_tx_LS11_flush");

    /* Execute the function */
    RC ret = rc_lsout11_out_250us();

    /* Check return value */
    CHECK_EQUAL(RC_SUCCESS, ret);

    /* Check modified variables */
    DOUBLES_EQUAL(0.5f, *p_f32_CuLSOut11, 0.0001);
    CHECK_EQUAL(0, *p_u8_time_LSOut11Short);
    DOUBLES_EQUAL(0.5f, *p_f32_CuLSOut11Short, 0.0001);
    CHECK_EQUAL(1, *p_u8_time_LSOut11CurrH);
    DOUBLES_EQUAL(0.5f, *p_f32_CuLSOut11CurrH, 0.0001);

    /* Check mock expectations */
    mock().checkExpectations();
}

/**
 * \brief Target: C4.a1 [u8_MaxTime_LSOut11CurrH <= u8_time_LSOut11CurrH]: lhs equal to rhs after C3=TRUE.
 * Decisions taken: C1=TRUE, C2=TRUE, C3=TRUE, C4=TRUE, C5=TRUE.
 *
 * \test
 * \pre Inputs: f32_CuLSOut11 = 0.0f; f32_LSOut11Short = 0.0f; u8_time_LSOut11Short = 0; u8_MaxTime_LSOut11Short
 * \pre   = 0; f32_CuLSOut11Short = 0.0f; f32_LSOut11CurrH = 0.0f; u8_time_LSOut11CurrH = 0;
 * \pre   u8_MaxTime_LSOut11CurrH = 1; f32_CuLSOut11CurrH = 0.0f.
 * \pre Mocks (in call order): sig_hwc_rx_cu_meas_11_get(returns .physical = 1.0f);
 * \pre   sig_hwc_tx_LS11_set(b_LSOut11_250us = FALSE); sig_hwc_tx_LS11_flush().
 * \post Return value RC_SUCCESS; f32_CuLSOut11 == 1.0f; u8_time_LSOut11Short == 1; f32_CuLSOut11Short == 1.0f;
 * \post   u8_time_LSOut11CurrH == 1; f32_CuLSOut11CurrH == 1.0f.
 */
TEST(rc_lsout11_out_250us, Testcase_1_6)
{
    /* Initialize input variables */
    *p_f32_CuLSOut11 = 0.0f;
    *p_f32_LSOut11Short = 0.0f;
    *p_u8_time_LSOut11Short = 0;
    *p_u8_MaxTime_LSOut11Short = 0;
    *p_f32_CuLSOut11Short = 0.0f;
    *p_f32_LSOut11CurrH = 0.0f;
    *p_u8_time_LSOut11CurrH = 0;
    *p_u8_MaxTime_LSOut11CurrH = 1;
    *p_f32_CuLSOut11CurrH = 0.0f;

    /* Configure mock expectations */
    volt_ratio_physical_t sig_hwc_rx_cu_meas_11_get_ret = {1.0f};

    mock().strictOrder();
    mock().expectOneCall("sig_hwc_rx_cu_meas_11_get")
          .andReturnValue(&sig_hwc_rx_cu_meas_11_get_ret);
    mock().expectOneCall("sig_hwc_tx_LS11_set")
          .withParameter("b_LSOut11_250us", (int)FALSE);
    mock().expectOneCall("sig_hwc_tx_LS11_flush");

    /* Execute the function */
    RC ret = rc_lsout11_out_250us();

    /* Check return value */
    CHECK_EQUAL(RC_SUCCESS, ret);

    /* Check modified variables */
    DOUBLES_EQUAL(1.0f, *p_f32_CuLSOut11, 0.0001);
    CHECK_EQUAL(1, *p_u8_time_LSOut11Short);
    DOUBLES_EQUAL(1.0f, *p_f32_CuLSOut11Short, 0.0001);
    CHECK_EQUAL(1, *p_u8_time_LSOut11CurrH);
    DOUBLES_EQUAL(1.0f, *p_f32_CuLSOut11CurrH, 0.0001);

    /* Check mock expectations */
    mock().checkExpectations();
}

/**
 * \brief Target: C4.a1 [u8_MaxTime_LSOut11CurrH <= u8_time_LSOut11CurrH]: lhs greater than rhs after C3=TRUE.
 * Decisions taken: C1=TRUE, C2=TRUE, C3=TRUE, C4=FALSE, C5=TRUE.
 *
 * \test
 * \pre Inputs: f32_CuLSOut11 = 0.0f; f32_LSOut11Short = 0.0f; u8_time_LSOut11Short = 0; u8_MaxTime_LSOut11Short
 * \pre   = 0; f32_CuLSOut11Short = 0.0f; f32_LSOut11CurrH = 0.0f; u8_time_LSOut11CurrH = 0;
 * \pre   u8_MaxTime_LSOut11CurrH = 2; f32_CuLSOut11CurrH = 0.0f.
 * \pre Mocks (in call order): sig_hwc_rx_cu_meas_11_get(returns .physical = 1.0f);
 * \pre   sig_hwc_tx_LS11_set(b_LSOut11_250us = FALSE); sig_hwc_tx_LS11_flush().
 * \post Return value RC_SUCCESS; f32_CuLSOut11 == 1.0f; u8_time_LSOut11Short == 1; f32_CuLSOut11Short == 1.0f;
 * \post   u8_time_LSOut11CurrH == 1.
 */
TEST(rc_lsout11_out_250us, Testcase_1_7)
{
    /* Initialize input variables */
    *p_f32_CuLSOut11 = 0.0f;
    *p_f32_LSOut11Short = 0.0f;
    *p_u8_time_LSOut11Short = 0;
    *p_u8_MaxTime_LSOut11Short = 0;
    *p_f32_CuLSOut11Short = 0.0f;
    *p_f32_LSOut11CurrH = 0.0f;
    *p_u8_time_LSOut11CurrH = 0;
    *p_u8_MaxTime_LSOut11CurrH = 2;
    *p_f32_CuLSOut11CurrH = 0.0f;

    /* Configure mock expectations */
    volt_ratio_physical_t sig_hwc_rx_cu_meas_11_get_ret = {1.0f};

    mock().strictOrder();
    mock().expectOneCall("sig_hwc_rx_cu_meas_11_get")
          .andReturnValue(&sig_hwc_rx_cu_meas_11_get_ret);
    mock().expectOneCall("sig_hwc_tx_LS11_set")
          .withParameter("b_LSOut11_250us", (int)FALSE);
    mock().expectOneCall("sig_hwc_tx_LS11_flush");

    /* Execute the function */
    RC ret = rc_lsout11_out_250us();

    /* Check return value */
    CHECK_EQUAL(RC_SUCCESS, ret);

    /* Check modified variables */
    DOUBLES_EQUAL(1.0f, *p_f32_CuLSOut11, 0.0001);
    CHECK_EQUAL(1, *p_u8_time_LSOut11Short);
    DOUBLES_EQUAL(1.0f, *p_f32_CuLSOut11Short, 0.0001);
    CHECK_EQUAL(1, *p_u8_time_LSOut11CurrH);

    /* Check mock expectations */
    mock().checkExpectations();
}

/**
 * \brief Target: C4.a1 [u8_MaxTime_LSOut11CurrH <= u8_time_LSOut11CurrH]: lhs equal to rhs after C3=FALSE.
 * Decisions taken: C1=TRUE, C2=TRUE, C3=FALSE, C4=TRUE, C5=TRUE.
 *
 * \test
 * \pre Inputs: f32_CuLSOut11 = 0.0f; f32_LSOut11Short = -1.0f; u8_time_LSOut11Short = 0;
 * \pre   u8_MaxTime_LSOut11Short = 0; f32_CuLSOut11Short = 0.0f; f32_LSOut11CurrH = 0.0f; u8_time_LSOut11CurrH
 * \pre   = 1; u8_MaxTime_LSOut11CurrH = 0; f32_CuLSOut11CurrH = 0.0f.
 * \pre Mocks (in call order): sig_hwc_rx_cu_meas_11_get(returns .physical = -1.0f);
 * \pre   sig_hwc_tx_LS11_set(b_LSOut11_250us = FALSE); sig_hwc_tx_LS11_flush().
 * \post Return value RC_SUCCESS; f32_CuLSOut11 == -1.0f; u8_time_LSOut11Short == 1; f32_CuLSOut11Short ==
 * \post   -1.0f; u8_time_LSOut11CurrH == 0; f32_CuLSOut11CurrH == -1.0f.
 */
TEST(rc_lsout11_out_250us, Testcase_1_8)
{
    /* Initialize input variables */
    *p_f32_CuLSOut11 = 0.0f;
    *p_f32_LSOut11Short = -1.0f;
    *p_u8_time_LSOut11Short = 0;
    *p_u8_MaxTime_LSOut11Short = 0;
    *p_f32_CuLSOut11Short = 0.0f;
    *p_f32_LSOut11CurrH = 0.0f;
    *p_u8_time_LSOut11CurrH = 1;
    *p_u8_MaxTime_LSOut11CurrH = 0;
    *p_f32_CuLSOut11CurrH = 0.0f;

    /* Configure mock expectations */
    volt_ratio_physical_t sig_hwc_rx_cu_meas_11_get_ret = {-1.0f};

    mock().strictOrder();
    mock().expectOneCall("sig_hwc_rx_cu_meas_11_get")
          .andReturnValue(&sig_hwc_rx_cu_meas_11_get_ret);
    mock().expectOneCall("sig_hwc_tx_LS11_set")
          .withParameter("b_LSOut11_250us", (int)FALSE);
    mock().expectOneCall("sig_hwc_tx_LS11_flush");

    /* Execute the function */
    RC ret = rc_lsout11_out_250us();

    /* Check return value */
    CHECK_EQUAL(RC_SUCCESS, ret);

    /* Check modified variables */
    DOUBLES_EQUAL(-1.0f, *p_f32_CuLSOut11, 0.0001);
    CHECK_EQUAL(1, *p_u8_time_LSOut11Short);
    DOUBLES_EQUAL(-1.0f, *p_f32_CuLSOut11Short, 0.0001);
    CHECK_EQUAL(0, *p_u8_time_LSOut11CurrH);
    DOUBLES_EQUAL(-1.0f, *p_f32_CuLSOut11CurrH, 0.0001);

    /* Check mock expectations */
    mock().checkExpectations();
}

/**
 * \brief Target: C4.a2 [0.0f == f32_CuLSOut11CurrH]: lhs not equal to rhs. Decisions taken: C1=TRUE, C2=TRUE,
 * C3=TRUE, C4=FALSE, C5=TRUE.
 *
 * \test
 * \pre Inputs: f32_CuLSOut11 = 0.0f; f32_LSOut11Short = 0.0f; u8_time_LSOut11Short = 0; u8_MaxTime_LSOut11Short
 * \pre   = 0; f32_CuLSOut11Short = 0.0f; f32_LSOut11CurrH = 0.0f; u8_time_LSOut11CurrH = 0;
 * \pre   u8_MaxTime_LSOut11CurrH = 0; f32_CuLSOut11CurrH = 1.0f.
 * \pre Mocks (in call order): sig_hwc_rx_cu_meas_11_get(returns .physical = 1.0f);
 * \pre   sig_hwc_tx_LS11_set(b_LSOut11_250us = FALSE); sig_hwc_tx_LS11_flush().
 * \post Return value RC_SUCCESS; f32_CuLSOut11 == 1.0f; u8_time_LSOut11Short == 1; f32_CuLSOut11Short == 1.0f;
 * \post   u8_time_LSOut11CurrH == 1.
 */
TEST(rc_lsout11_out_250us, Testcase_1_9)
{
    /* Initialize input variables */
    *p_f32_CuLSOut11 = 0.0f;
    *p_f32_LSOut11Short = 0.0f;
    *p_u8_time_LSOut11Short = 0;
    *p_u8_MaxTime_LSOut11Short = 0;
    *p_f32_CuLSOut11Short = 0.0f;
    *p_f32_LSOut11CurrH = 0.0f;
    *p_u8_time_LSOut11CurrH = 0;
    *p_u8_MaxTime_LSOut11CurrH = 0;
    *p_f32_CuLSOut11CurrH = 1.0f;

    /* Configure mock expectations */
    volt_ratio_physical_t sig_hwc_rx_cu_meas_11_get_ret = {1.0f};

    mock().strictOrder();
    mock().expectOneCall("sig_hwc_rx_cu_meas_11_get")
          .andReturnValue(&sig_hwc_rx_cu_meas_11_get_ret);
    mock().expectOneCall("sig_hwc_tx_LS11_set")
          .withParameter("b_LSOut11_250us", (int)FALSE);
    mock().expectOneCall("sig_hwc_tx_LS11_flush");

    /* Execute the function */
    RC ret = rc_lsout11_out_250us();

    /* Check return value */
    CHECK_EQUAL(RC_SUCCESS, ret);

    /* Check modified variables */
    DOUBLES_EQUAL(1.0f, *p_f32_CuLSOut11, 0.0001);
    CHECK_EQUAL(1, *p_u8_time_LSOut11Short);
    DOUBLES_EQUAL(1.0f, *p_f32_CuLSOut11Short, 0.0001);
    CHECK_EQUAL(1, *p_u8_time_LSOut11CurrH);

    /* Check mock expectations */
    mock().checkExpectations();
}

/**
 * \brief Target: C5.a2 [0.0f != f32_CuLSOut11Short]: lhs not equal to rhs after C2=FALSE. Decisions taken:
 * C1=TRUE, C2=FALSE, C3=TRUE, C4=TRUE, C5=TRUE.
 *
 * \test
 * \pre Inputs: f32_CuLSOut11 = 1.0f; f32_LSOut11Short = 0.0f; u8_time_LSOut11Short = 0; u8_MaxTime_LSOut11Short
 * \pre   = 0; f32_CuLSOut11Short = 1.0f; f32_LSOut11CurrH = 0.0f; u8_time_LSOut11CurrH = 0;
 * \pre   u8_MaxTime_LSOut11CurrH = 0; f32_CuLSOut11CurrH = 0.0f.
 * \pre Mocks (in call order): sig_hwc_rx_cu_meas_11_get(returns .physical = 0.0f);
 * \pre   sig_hwc_tx_LS11_set(b_LSOut11_250us = FALSE); sig_hwc_tx_LS11_flush().
 * \post Return value RC_SUCCESS; f32_CuLSOut11 == 0.0f; u8_time_LSOut11Short == 1; u8_time_LSOut11CurrH == 1;
 * \post   f32_CuLSOut11CurrH == 0.0f.
 */
TEST(rc_lsout11_out_250us, Testcase_1_10)
{
    /* Initialize input variables */
    *p_f32_CuLSOut11 = 1.0f;
    *p_f32_LSOut11Short = 0.0f;
    *p_u8_time_LSOut11Short = 0;
    *p_u8_MaxTime_LSOut11Short = 0;
    *p_f32_CuLSOut11Short = 1.0f;
    *p_f32_LSOut11CurrH = 0.0f;
    *p_u8_time_LSOut11CurrH = 0;
    *p_u8_MaxTime_LSOut11CurrH = 0;
    *p_f32_CuLSOut11CurrH = 0.0f;

    /* Configure mock expectations */
    volt_ratio_physical_t sig_hwc_rx_cu_meas_11_get_ret = {0.0f};

    mock().strictOrder();
    mock().expectOneCall("sig_hwc_rx_cu_meas_11_get")
          .andReturnValue(&sig_hwc_rx_cu_meas_11_get_ret);
    mock().expectOneCall("sig_hwc_tx_LS11_set")
          .withParameter("b_LSOut11_250us", (int)FALSE);
    mock().expectOneCall("sig_hwc_tx_LS11_flush");

    /* Execute the function */
    RC ret = rc_lsout11_out_250us();

    /* Check return value */
    CHECK_EQUAL(RC_SUCCESS, ret);

    /* Check modified variables */
    DOUBLES_EQUAL(0.0f, *p_f32_CuLSOut11, 0.0001);
    CHECK_EQUAL(1, *p_u8_time_LSOut11Short);
    CHECK_EQUAL(1, *p_u8_time_LSOut11CurrH);
    DOUBLES_EQUAL(0.0f, *p_f32_CuLSOut11CurrH, 0.0001);

    /* Check mock expectations */
    mock().checkExpectations();
}

/**
 * \brief Target: u8_time_LSOut11Short ++ executed at the unsigned type limit (wrap-around). Decisions taken:
 * C1=TRUE, C2=TRUE, C3=TRUE, C4=TRUE, C5=TRUE.
 *
 * \test
 * \pre Inputs: f32_CuLSOut11 = 0.0f; f32_LSOut11Short = 0.0f; u8_time_LSOut11Short = 255;
 * \pre   u8_MaxTime_LSOut11Short = 0; f32_CuLSOut11Short = 0.0f; f32_LSOut11CurrH = 0.0f; u8_time_LSOut11CurrH
 * \pre   = 0; u8_MaxTime_LSOut11CurrH = 0; f32_CuLSOut11CurrH = 0.0f.
 * \pre Mocks (in call order): sig_hwc_rx_cu_meas_11_get(returns .physical = 1.0f);
 * \pre   sig_hwc_tx_LS11_set(b_LSOut11_250us = FALSE); sig_hwc_tx_LS11_flush().
 * \post Return value RC_SUCCESS; f32_CuLSOut11 == 1.0f; u8_time_LSOut11Short == 0; f32_CuLSOut11Short == 1.0f;
 * \post   u8_time_LSOut11CurrH == 1; f32_CuLSOut11CurrH == 1.0f.
 */
TEST(rc_lsout11_out_250us, Testcase_1_11)
{
    /* Initialize input variables */
    *p_f32_CuLSOut11 = 0.0f;
    *p_f32_LSOut11Short = 0.0f;
    *p_u8_time_LSOut11Short = 255;
    *p_u8_MaxTime_LSOut11Short = 0;
    *p_f32_CuLSOut11Short = 0.0f;
    *p_f32_LSOut11CurrH = 0.0f;
    *p_u8_time_LSOut11CurrH = 0;
    *p_u8_MaxTime_LSOut11CurrH = 0;
    *p_f32_CuLSOut11CurrH = 0.0f;

    /* Configure mock expectations */
    volt_ratio_physical_t sig_hwc_rx_cu_meas_11_get_ret = {1.0f};

    mock().strictOrder();
    mock().expectOneCall("sig_hwc_rx_cu_meas_11_get")
          .andReturnValue(&sig_hwc_rx_cu_meas_11_get_ret);
    mock().expectOneCall("sig_hwc_tx_LS11_set")
          .withParameter("b_LSOut11_250us", (int)FALSE);
    mock().expectOneCall("sig_hwc_tx_LS11_flush");

    /* Execute the function */
    RC ret = rc_lsout11_out_250us();

    /* Check return value */
    CHECK_EQUAL(RC_SUCCESS, ret);

    /* Check modified variables */
    DOUBLES_EQUAL(1.0f, *p_f32_CuLSOut11, 0.0001);
    CHECK_EQUAL(0, *p_u8_time_LSOut11Short);
    DOUBLES_EQUAL(1.0f, *p_f32_CuLSOut11Short, 0.0001);
    CHECK_EQUAL(1, *p_u8_time_LSOut11CurrH);
    DOUBLES_EQUAL(1.0f, *p_f32_CuLSOut11CurrH, 0.0001);

    /* Check mock expectations */
    mock().checkExpectations();
}

/**
 * \brief Target: u8_time_LSOut11CurrH ++ executed at the unsigned type limit (wrap-around). Decisions taken:
 * C1=TRUE, C2=TRUE, C3=TRUE, C4=TRUE, C5=TRUE.
 *
 * \test
 * \pre Inputs: f32_CuLSOut11 = 0.0f; f32_LSOut11Short = 0.0f; u8_time_LSOut11Short = 0; u8_MaxTime_LSOut11Short
 * \pre   = 0; f32_CuLSOut11Short = 0.0f; f32_LSOut11CurrH = 0.0f; u8_time_LSOut11CurrH = 255;
 * \pre   u8_MaxTime_LSOut11CurrH = 0; f32_CuLSOut11CurrH = 0.0f.
 * \pre Mocks (in call order): sig_hwc_rx_cu_meas_11_get(returns .physical = 1.0f);
 * \pre   sig_hwc_tx_LS11_set(b_LSOut11_250us = FALSE); sig_hwc_tx_LS11_flush().
 * \post Return value RC_SUCCESS; f32_CuLSOut11 == 1.0f; u8_time_LSOut11Short == 1; f32_CuLSOut11Short == 1.0f;
 * \post   u8_time_LSOut11CurrH == 0; f32_CuLSOut11CurrH == 1.0f.
 */
TEST(rc_lsout11_out_250us, Testcase_1_12)
{
    /* Initialize input variables */
    *p_f32_CuLSOut11 = 0.0f;
    *p_f32_LSOut11Short = 0.0f;
    *p_u8_time_LSOut11Short = 0;
    *p_u8_MaxTime_LSOut11Short = 0;
    *p_f32_CuLSOut11Short = 0.0f;
    *p_f32_LSOut11CurrH = 0.0f;
    *p_u8_time_LSOut11CurrH = 255;
    *p_u8_MaxTime_LSOut11CurrH = 0;
    *p_f32_CuLSOut11CurrH = 0.0f;

    /* Configure mock expectations */
    volt_ratio_physical_t sig_hwc_rx_cu_meas_11_get_ret = {1.0f};

    mock().strictOrder();
    mock().expectOneCall("sig_hwc_rx_cu_meas_11_get")
          .andReturnValue(&sig_hwc_rx_cu_meas_11_get_ret);
    mock().expectOneCall("sig_hwc_tx_LS11_set")
          .withParameter("b_LSOut11_250us", (int)FALSE);
    mock().expectOneCall("sig_hwc_tx_LS11_flush");

    /* Execute the function */
    RC ret = rc_lsout11_out_250us();

    /* Check return value */
    CHECK_EQUAL(RC_SUCCESS, ret);

    /* Check modified variables */
    DOUBLES_EQUAL(1.0f, *p_f32_CuLSOut11, 0.0001);
    CHECK_EQUAL(1, *p_u8_time_LSOut11Short);
    DOUBLES_EQUAL(1.0f, *p_f32_CuLSOut11Short, 0.0001);
    CHECK_EQUAL(0, *p_u8_time_LSOut11CurrH);
    DOUBLES_EQUAL(1.0f, *p_f32_CuLSOut11CurrH, 0.0001);

    /* Check mock expectations */
    mock().checkExpectations();
}

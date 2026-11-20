RC rc_lsout11_out_250us ( VO )
{
   /***** local variables *****/
   BO b_LSOut11_250us = FALSE; /* enable/disable the output "LS_11_OUT" from the 250us cycle */

   /****************************************************************************************************************
   * section: update static c-file variables
   ****************************************************************************************************************/

   f32_CuLSOut11 = ( sig_hwc_rx_cu_meas_11_get().physical ); /* update static variable */

   /****************************************************************************************************************
   * section: short circuit detection
   ****************************************************************************************************************/

   if ( f32_LSOut11Short <= f32_CuLSOut11 )
   {
      u8_time_LSOut11Short ++;
   }
   else
   {
      u8_time_LSOut11Short = 0;
   }

   if (    ( u8_MaxTime_LSOut11Short <= u8_time_LSOut11Short )
        && ( 0.0f == f32_CuLSOut11Short )
      )
   {
      f32_CuLSOut11Short = f32_CuLSOut11;
   }

   /****************************************************************************************************************
   * section: over current detection
   ****************************************************************************************************************/

   if ( f32_LSOut11CurrH <= f32_CuLSOut11 )
   {
      u8_time_LSOut11CurrH ++;
   }
   else
   {
      u8_time_LSOut11CurrH = 0;
   }

   if (    ( u8_MaxTime_LSOut11CurrH <= u8_time_LSOut11CurrH )
        && ( 0.0f == f32_CuLSOut11CurrH )
      )
   {
      f32_CuLSOut11CurrH = f32_CuLSOut11;
   }

   /****************************************************************************************************************
   * section: control the output port
   ****************************************************************************************************************/

   if (    ( 0.0f != f32_CuLSOut11CurrH )
        || ( 0.0f != f32_CuLSOut11Short )
      )
   {
      b_LSOut11_250us = FALSE;
   }
   else
   {
      if ( FALSE != b_LSOut11_10ms )
      {
         b_LSOut11_250us =  TRUE;
      }
      else
      {
         b_LSOut11_250us = FALSE;
      }
   }

   /***************************************************************************************************************/

   (VO) sig_hwc_tx_LS11_set ( b_LSOut11_250us ); /* update sigpool variable */
   (VO) sig_hwc_tx_LS11_flush ();

   return RC_SUCCESS;
}
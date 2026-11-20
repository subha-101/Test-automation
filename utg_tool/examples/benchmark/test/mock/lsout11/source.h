/**
* \file mock_lsout11_out.h
* \brief Mocks and stubs for lsout11_out.
* \author Subhasish Singha <subhasish.singha1@kiongroup.com>
*/

#ifndef MOCK_LSOUT11_OUT_H
#define MOCK_LSOUT11_OUT_H

#include "../../../src/bsw/pal/types.h"
#include "../../../src/share/types_common.h"
#include "../../../src/app/app_diag/dtc/dtc_lst_safety1.h"
#include "../../../src/bsw/cfg/dtc_cfg.h"

#define EQU_REQT_RELAYOFF        U32_CONST ( 0x00000001 )
#define EQU_REQT_MCONTOFF        U32_CONST ( 0x00000002 )
#define EQU_REQT_POWRPOFF        U32_CONST ( 0x00000004 )
#define EQU_REQT_USENSOFF        U32_CONST ( 0x00000008 )
#define EQU_REQT_CASTWOFF        U32_CONST ( 0x00000010 )
#define EQU_REQT_FANIMOFF        U32_CONST ( 0x00000020 )
#define EQU_REQT_COX30OFF        U32_CONST ( 0x00000040 )
                                                         
#define EQU_REQT_COX06OFF        U32_CONST ( 0x00000080 )
                                                         
#define EQU_REQT_MMI_SAFE_BIT8   U32_CONST ( 0x00000100 )
                                                         
#define EQU_REQT_IOEXTOFF        U32_CONST ( 0x00000200 )
                                                         
#define EQU_REQT_HORNIOFF        U32_CONST ( 0x00000400 )
#define EQU_REQT_US13VOFF        U32_CONST ( 0x00000800 )
#define EQU_REQT_KCURELOFF       U32_CONST ( 0x00001000 )
                                                         
#define EQU_REQT_ADDOUTSOFF      U32_CONST ( 0x00002000 )

typedef enum sih_flag_e
{
   SIH_SAFETY1_DIS_RELEASE_TOG = 0 ,
   SIH_TRAC_BKSTOP             ,   
   SIH_TRAC_BRKJAM             ,   
   SIH_TRAC_ECOMBLUEQ          ,   
   SIH_TRAC_BYDRIV             ,   
   SIH_TRAC_BYSTOP             ,   
   SIH_TRAC_CEDE               ,   
   SIH_TRAC_CRSW               ,   
   SIH_TRAC_CUSTDEF            ,   
   SIH_TRAC_DEBFINV            ,   
   SIH_TRAC_DEPRSWITCH         ,   
   SIH_TRAC_FLY                ,   
   SIH_TRAC_FREEW              ,   
   SIH_TRAC_IPCTRLOFF          ,   
   SIH_TRAC_RIDE               ,   
   SIH_TRAC_SOFTSTOP           ,   
   SIH_TRAC_SPINDO             ,   
   SIH_TRAC_SPINDORE           ,   
   SIH_TRAC_SPFULM             ,   
   SIH_TRAC_SPLM18RE           ,   
   SIH_TRAC_SPLM18NR           ,   
   SIH_TRAC_SPLM30             ,   
   SIH_TRAC_SPLM40             ,   
   SIH_TRAC_SPLM45             ,   
   SIH_TRAC_SPLM60             ,   
   SIH_TRAC_SPLMLIION          ,   
   SIH_TRAC_SPLMSPPR           ,   
   SIH_TRAC_SPMALI1            ,   
   SIH_TRAC_SPMALI2            ,   
   SIH_TRAC_SPMALICUTOUT1      ,   
   SIH_TRAC_SPMALICUTOUT2      ,   
   SIH_TRAC_SPPRSWITCH         ,   
   SIH_TRAC_SPSOFTLA           ,   
   SIH_TRAC_SPLM_CO1           ,   
   SIH_TRAC_SPLM_CO2           ,   
   SIH_TRAC_SPLMAULILO         ,   
   SIH_TRAC_DUMMY2             ,   
   SIH_TRAC_SRWS               ,   
   SIH_TRAC_SRWSAGW            ,   
   SIH_TRAC_TIRE               ,   
   SIH_TRAC_TIREBY             ,   
   SIH_TRAC_TRACTPOWRED_LIB    ,   
   SIH_TRAC_TRCMDRE            ,   
   SIH_TRAC_TURTLE             ,   
   SIH_TRAC_WALK               ,   
   SIH_TRAC_WALKUF             ,   
   SIH_HYDR_BLUEQ              ,   
   SIH_HYDR_CUSTRABB           ,   
   SIH_HYDR_ISENUP             ,   
   SIH_HYDR_LISLOW             ,   
   SIH_HYDR_LISTOPHARD         ,   
   SIH_HYDR_LISTOPSOFT         ,   
   SIH_HYDR_LMPUMPOC           ,   
   SIH_HYDR_LOSTOP             ,   
   SIH_HYDR_MALIBOON           ,   
   SIH_HYDR_MALOSOFTLA         ,   
   SIH_HYDR_PRMALIHI           ,   
   SIH_HYDR_NOINLIMAIN         ,   
   SIH_HYDR_NOINLIREAR         ,   
   SIH_HYDR_NOINLOMAIN         ,   
   SIH_HYDR_NOINLOREAR         ,   
   SIH_HYDR_NOMALIEMU2         ,   
   SIH_HYDR_NOMALIMAIN         ,   
   SIH_HYDR_NOMALIMLS          ,   
   SIH_HYDR_NOMALIREAR         ,   
   SIH_HYDR_NOMALOEMU2         ,   
   SIH_HYDR_NOMALOMAIN         ,   
   SIH_HYDR_NOMALOMLS          ,   
   SIH_HYDR_NOMALOREAR         ,   
   SIH_HYDR_PALISTOP           ,   
   SIH_HYDR_PALOSTOP           ,   
   SIH_HYDR_POWSAVE2           ,   
   SIH_HYDR_PWM_LIMIT          ,   
   SIH_HYDR_SOFTSTOP           ,   
   SIH_HYDR_TURTLE             ,   
   SIH_HYDR_WAYSSTOP           ,   
   SIH_ACTU_ALLOFF             ,   
   SIH_ACTU_CASTWOFF           ,   
   SIH_ACTU_NOTUSED_1          ,   
   SIH_ACTU_HORNIOFF           ,   
   SIH_ACTU_NOTUSED_2          ,   
   SIH_ACTU_KCURELOFF          ,   
   SIH_ACTU_MCONTOFF           ,   
   SIH_ACTU_POWRPOFF           ,   
   SIH_ACTU_RELAYOFF           ,   
   SIH_ACTU_USENSOFF           ,   
   SIH_ACTU_US13VOFF           ,   
   SIH_HYDR_NOMALIINCH         ,   
   SIH_HYDR_NOMALOINCH         ,   
   SIH_HYDR_NOMALIINCHREAR     ,   
   SIH_HYDR_NOMALOINCHREAR     ,   
   SIH_HYDR_MALISOFTSTOP       ,   
   SIH_HYDR_MALOSOFTSTOP       ,   
   SIH_HYDR_AUTOLISTOP         ,   
   SIH_HYDR_AUTOLOSTOP         ,   
   SIH_HYDR_INLISOFTSTOP       ,   
   SIH_HYDR_INLOSOFTSTOP       ,   
   SIH_HYDR_STANDSTACK         ,   
   SIH_HYDR_INDOMAHINR         ,   
   SIH_TRAC_SPSMDDC            ,   
   SIH_ACTU_ADDOUTSOFF         ,   
   SIH_HYDR_PRINLIHI           ,   
   SIH_TRAC_ACPRSWITCH         ,   
   SIH_TRAC_SMOOTHPERF         ,   
   SIH_HYDR_KCULIMITLI         ,   
   SIH_HYDR_KCULIMITLO         ,   
   SIH_TRAC_ANTIVIBRA          ,   
   SIH_TRAC_SPCORED1           ,   
   SIH_TRAC_SPCORED2           ,   
   SIH_TRAC_SPDOUBST           ,   
   SIH_TRAC_AULOGRESMOD        ,   
   SIH_HYDR_AULOGRESMOD        ,   
   SIH_TRAC_WHSGSPRED          ,   
   SIH_TRAC_WHSGSPREDWR        ,   
   SIH_TRAC_SOFTSTOPFO         ,   
   SIH_TRAC_SOFTSTOPBA         ,   
   SIH_TRAC_SOFTSTOPBO         ,   
   SIH_TRAC_LODETSPRED         ,   
   SIH_TRAC_LODETSPREDWR        ,   
   SIH_TRAC_SPMALICUTOUT1WR    ,   
   SIH_TRAC_SPMALICUTOUT2WR    ,   
   SIH_TRAC_SPMALICUTOUT3         ,   
   SIH_TRAC_SPMALICUTOUT3WR        ,   
   SIH_CNT                     ,   
} sih_flag_t;


U32 sig_ReqT_get(void);
BO sih_get_flag(sih_flag_t flag);
VO sig_hwc_tx_LS11_flush(void);
VO sig_hwc_tx_LS11_set(BO b_LSOut11_250us);
BO sig_ipc_rx_LorryDetLight_get(void);
volt_ratio_physical_t sig_hwc_rx_cu_meas_11_get(void);
S16 sig_LS11CuDTC_set(S16 value);    
S16 sig_LS11OverCur_set(S16 value);  
S16 sig_LS11ShortCirc_set(S16 value);

#endif /* MOCK_LSOUT11_OUT_H */
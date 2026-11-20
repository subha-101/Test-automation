/* ===================================================================================================
 * PARSE-TIME PRELUDE  (ASSUMPTIONS - replace with the real declarations of your project)
 * source.c only contains the function body.  The declarations below were NOT provided by the user:
 *   - volt_ratio_physical_t : layout inferred from the spec example  volt_ratio_physical_t x = {0.0f};  and ".physical"
 *   - file-scope variables  : names come from source.c, the TYPES are an assumption (F32 / U8 / BO).
 * ================================================================================================== */
typedef struct { F32 physical; } volt_ratio_physical_t;

static F32 f32_CuLSOut11;
static F32 f32_LSOut11Short;
static U8  u8_time_LSOut11Short;
static U8  u8_MaxTime_LSOut11Short;
static F32 f32_CuLSOut11Short;
static F32 f32_LSOut11CurrH;
static U8  u8_time_LSOut11CurrH;
static U8  u8_MaxTime_LSOut11CurrH;
static F32 f32_CuLSOut11CurrH;
static BO  b_LSOut11_10ms;

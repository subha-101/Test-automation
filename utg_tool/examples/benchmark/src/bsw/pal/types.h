/* types.h -- fixture reproduced from the typedefs pasted by the user (Linde MH types.h).
   Only declarations relevant for parsing are kept; the CONST, MIN and MAX helper macros are omitted. */
#ifndef TYPES_H_INCLUDED
#define TYPES_H_INCLUDED

typedef unsigned char U8;
typedef signed char S8;
typedef unsigned char UX8;
typedef signed char SX8;
typedef unsigned short U16;
typedef signed short S16;
typedef unsigned short UX16;
typedef signed short SX16;
typedef unsigned long U32;
typedef signed long S32;
typedef unsigned long UX32;
typedef signed long SX32;
typedef unsigned long long U64;
typedef signed long long S64;
typedef signed char CH;
typedef unsigned int UP;
typedef signed int SP;
typedef float F32;
typedef double F64;
typedef unsigned char BO;
typedef void VO;

#ifndef FALSE
#   define FALSE 0
#endif
#ifndef TRUE
#   define TRUE  (!FALSE)
#endif

typedef enum
{
   RC_SUCCESS = 0, RC_ERROR = -1, RC_ERROR_NULL = -2, RC_ERROR_ZERO = -3, RC_ERROR_MEMORY = -4,
   RC_ERROR_RANGE = -5, RC_ERROR_OVERRUN = -6, RC_ERROR_UNDERRUN = -7, RC_ERROR_BUFFER_FULL = -8,
   RC_ERROR_BUFFER_EMTPY = -9, RC_ERROR_BUSY = -10, RC_ERROR_TIME_OUT = -11, RC_ERROR_OPEN = -12,
   RC_ERROR_CHECKSUM = -13, RC_ERROR_READ_ONLY = -14, RC_ERROR_WRITE_ONLY = -15, RC_ERROR_INVALID = -16,
   RC_ERROR_READ_FAILS = -17, RC_ERROR_WRITE_FAILS = -18, RC_ERROR_NOT_MATCH = -19,
   RC_ERROR_FILE_ACCESS = -21, RC_ERROR_FILE_SIZE_UNDERRUN = -22, RC_ERROR_FILE_SIZE_OVERRUN = -23,
   RC_ERROR_VERIFY = -24, RC_ERROR_NOT_FOUND = -25, RC_ERROR_WRITE_INVALID_LENGTH = -26
} RC;

#endif

#ifndef TRANSPORT_TEST_ARDUINO_H
#define TRANSPORT_TEST_ARDUINO_H
extern int transportCriticalDepth;
#define taskENTER_CRITICAL() (++transportCriticalDepth)
#define taskEXIT_CRITICAL() (--transportCriticalDepth)
#endif

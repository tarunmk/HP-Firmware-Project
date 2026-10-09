#include <Arduino_FreeRTOS.h>

static void heartbeatTask(void *pvParameters)
{
    (void)pvParameters;

    for (;;) {
        vTaskDelay(pdMS_TO_TICKS(1000));
    }
}

void setup()
{
    BaseType_t result = xTaskCreate(
        heartbeatTask,
        "Heartbeat",
        128,
        NULL,
        1,
        NULL
    );

    configASSERT(result == pdPASS);
}

void loop()
{
    // FreeRTOS manages the task after the scheduler starts.
}

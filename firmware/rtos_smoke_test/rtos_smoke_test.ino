#include <Arduino_FreeRTOS.h>

static void heartbeatTask(void *pvParameters)
{
    (void)pvParameters;

    pinMode(LED_BUILTIN, OUTPUT);

    for (;;) {
        digitalWrite(LED_BUILTIN, HIGH);
        vTaskDelay(pdMS_TO_TICKS(500));

        digitalWrite(LED_BUILTIN, LOW);
        vTaskDelay(pdMS_TO_TICKS(500));
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
}
#include <Arduino_FreeRTOS.h>

static constexpr uint8_t LED_PIN = LED_BUILTIN;
static constexpr uint16_t SENSOR_SAMPLE_PERIOD_MS = 1000;

struct SensorReading
{
    uint32_t timestamp_ms;
    float temperature_c;
};

static SensorReading latestReading = {0, 0.0f};

static float readSyntheticTemperature()
{
    // Temporary deterministic sensor signal.
    // A physical temperature sensor can replace this function later.
    static float temperature = 24.0f;
    temperature += 0.25f;

    if (temperature > 30.0f)
    {
        temperature = 24.0f;
    }

    return temperature;
}

static void sensorTask(void *pvParameters)
{
    (void)pvParameters;

    pinMode(LED_PIN, OUTPUT);

    TickType_t lastWakeTime = xTaskGetTickCount();
    const TickType_t samplePeriod =
        pdMS_TO_TICKS(SENSOR_SAMPLE_PERIOD_MS);

    for (;;)
    {
        latestReading.timestamp_ms =
            static_cast<uint32_t>(millis());

        latestReading.temperature_c =
            readSyntheticTemperature();

        digitalWrite(LED_PIN, !digitalRead(LED_PIN));

        vTaskDelayUntil(&lastWakeTime, samplePeriod);
    }
}

void setup()
{
    const BaseType_t result = xTaskCreate(
        sensorTask,
        "Sensor",
        192,
        nullptr,
        1,
        nullptr);

    configASSERT(result == pdPASS);
}

void loop()
{
}
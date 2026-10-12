
#include <Arduino_FreeRTOS.h>
#include "telemetry_protocol.h"
#include <string.h>
#include <stdlib.h>

static constexpr uint8_t LED_PIN = LED_BUILTIN;
static constexpr uint16_t DEFAULT_SAMPLE_PERIOD_MS = 1000;
static constexpr uint16_t MIN_SAMPLE_PERIOD_MS = 100;
static constexpr uint16_t MAX_SAMPLE_PERIOD_MS = 5000;
static constexpr uint16_t LOW_POWER_SAMPLE_PERIOD_MS = 5000;
static constexpr uint8_t COMMAND_BUFFER_SIZE = 32;
static constexpr uint8_t TMP36_PIN = A0;
static constexpr float ADC_REFERENCE_VOLTAGE = 5.0f;
static constexpr float TMP36_OFFSET_VOLTAGE = 0.500f;
static constexpr float TMP36_VOLTS_PER_C = 0.010f;

struct SensorReading
{
    uint32_t timestamp_ms;
    float temperature_c;
};

static SensorReading latestReading = {0, 0.0f};
static uint8_t telemetryFrame[TelemetryProtocol::MAX_FRAME_SIZE];
static uint16_t telemetrySequence = 0;

// User-configured normal-mode sampling interval.
static uint16_t samplePeriodMs = DEFAULT_SAMPLE_PERIOD_MS;

static bool streamingEnabled = true;
static bool lowPowerMode = false;

static float readTemperatureC()
{
    const int rawAdc = analogRead(TMP36_PIN);

    const float voltage =
        rawAdc * (ADC_REFERENCE_VOLTAGE / 1023.0f);

    return (voltage - TMP36_OFFSET_VOLTAGE)
           / TMP36_VOLTS_PER_C;
}

static uint16_t getEffectiveSamplePeriodMs()
{
    return lowPowerMode
        ? LOW_POWER_SAMPLE_PERIOD_MS
        : samplePeriodMs;
}

static void processCommand(char *command)
{
    if (strncmp(command, "RATE,", 5) == 0)
    {
        char *end = nullptr;
        long requestedPeriod = strtol(command + 5, &end, 10);

        if (end == command + 5 || *end != '\0' ||
            requestedPeriod < MIN_SAMPLE_PERIOD_MS ||
            requestedPeriod > MAX_SAMPLE_PERIOD_MS)
        {
            Serial.println("ERR,RATE");
            return;
        }

        samplePeriodMs = static_cast<uint16_t>(requestedPeriod);
        Serial.println("OK,RATE");
    }
    else if (strcmp(command, "POWER_MODE,LOW") == 0)
    {
        lowPowerMode = true;
        Serial.println("OK,POWER_MODE,LOW");
    }
    else if (strcmp(command, "POWER_MODE,NORMAL") == 0)
    {
        lowPowerMode = false;
        Serial.println("OK,POWER_MODE,NORMAL");
    }
    else if (strcmp(command, "STREAM,0") == 0)
    {
        streamingEnabled = false;
        Serial.println("OK,STREAM,0");
    }
    else if (strcmp(command, "STREAM,1") == 0)
    {
        streamingEnabled = true;
        Serial.println("OK,STREAM,1");
    }
    else if (strcmp(command, "STATUS") == 0)
    {
        Serial.print("STATUS,");
        Serial.print(samplePeriodMs);
        Serial.print(",");
        Serial.print(streamingEnabled ? 1 : 0);
        Serial.print(",");
        Serial.println(lowPowerMode ? "LOW" : "NORMAL");
    }
    else if (strcmp(command, "POWER_STATUS") == 0)
    {
        Serial.print("POWER_STATUS,");
        Serial.println(lowPowerMode ? "LOW" : "NORMAL");
    }
    else if (command[0] != '\0')
    {
        Serial.println("ERR,UNKNOWN_COMMAND");
    }
}


static void processSerialCommands()
{
    static char commandBuffer[COMMAND_BUFFER_SIZE];
    static uint8_t commandLength = 0;
    static bool discardingOverlongCommand = false;

    while (Serial.available() > 0)
    {
        char incoming = static_cast<char>(Serial.read());

        if (incoming == '\r')
        {
            continue;
        }

        if (incoming == '\n')
        {
            if (discardingOverlongCommand)
            {
                Serial.println("ERR,COMMAND_TOO_LONG");
                discardingOverlongCommand = false;
                commandLength = 0;
                continue;
            }

            commandBuffer[commandLength] = '\0';
            processCommand(commandBuffer);
            commandLength = 0;
            continue;
        }

        if (discardingOverlongCommand)
        {
            continue;
        }

        if (commandLength < COMMAND_BUFFER_SIZE - 1)
        {
            commandBuffer[commandLength++] = incoming;
        }
        else
        {
            // Discard the entire oversized command through its newline.
            commandLength = 0;
            discardingOverlongCommand = true;
        }
    }
}

static void sensorTask(void *pvParameters)
{
    (void)pvParameters;

    pinMode(LED_PIN, OUTPUT);

    TickType_t lastSampleTick = xTaskGetTickCount();

    for (;;)
    {
        // Keep command processing responsive in both power modes.
        processSerialCommands();

        TickType_t now = xTaskGetTickCount();
        TickType_t periodTicks =
            pdMS_TO_TICKS(getEffectiveSamplePeriodMs());

        if (periodTicks == 0)
        {
            periodTicks = 1;
        }

        if (static_cast<TickType_t>(now - lastSampleTick) >=
            periodTicks)
        {
            lastSampleTick = now;

            latestReading.timestamp_ms =
                static_cast<uint32_t>(millis());

            latestReading.temperature_c = readTemperatureC();

            if (streamingEnabled)
            {
                const bool encoded =
                    TelemetryProtocol::encodeTelemetry(
                        telemetryFrame,
                        sizeof(telemetryFrame),
                        telemetrySequence,
                        static_cast<uint64_t>(
                            latestReading.timestamp_ms),
                        latestReading.temperature_c);

                if (encoded)
                {
                    Serial.write(
                        telemetryFrame,
                        sizeof(telemetryFrame));

                    ++telemetrySequence;
                }
            }

            // Avoid unnecessary LED switching in low-power mode.
            if (!lowPowerMode)
            {
                digitalWrite(LED_PIN, !digitalRead(LED_PIN));
            }
        }

        vTaskDelay(pdMS_TO_TICKS(10));
    }
}

void setup()
{
    Serial.begin(115200);

    const BaseType_t result = xTaskCreate(
        sensorTask,
        "Sensor",
        256,
        nullptr,
        1,
        nullptr);

    configASSERT(result == pdPASS);
}

void loop()
{
}

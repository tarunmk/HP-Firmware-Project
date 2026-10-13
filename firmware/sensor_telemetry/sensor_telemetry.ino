
#include <Arduino_FreeRTOS.h>
#include "telemetry_protocol.h"
#include <string.h>
#include <stdlib.h>

// Hardware and sampling configuration.
static constexpr uint8_t LED_PIN = LED_BUILTIN;
static constexpr uint16_t DEFAULT_SAMPLE_PERIOD_MS = 1000;
static constexpr uint16_t MIN_SAMPLE_PERIOD_MS = 100;
static constexpr uint16_t MAX_SAMPLE_PERIOD_MS = 5000;

// LOW mode uses a fixed, slower sampling interval. This changes the
// sampling behavior but does not guarantee a measured power reduction.
static constexpr uint16_t LOW_POWER_SAMPLE_PERIOD_MS = 5000;

static constexpr uint8_t COMMAND_BUFFER_SIZE = 32;
static constexpr uint8_t TMP36_PIN = A0;

// TMP36 conversion assumes a 5 V ADC reference and a sensor output
// of 500 mV at 0 °C, increasing by 10 mV per degree Celsius.
static constexpr float ADC_REFERENCE_VOLTAGE = 5.0f;
static constexpr float TMP36_OFFSET_VOLTAGE = 0.500f;
static constexpr float TMP36_VOLTS_PER_C = 0.010f;

// Holds the most recently sampled temperature and its device timestamp.
struct SensorReading
{
    uint32_t timestamp_ms;
    float temperature_c;
};

static SensorReading latestReading = {0, 0.0f};

// Reused transmit buffer avoids allocating memory for every telemetry frame.
static uint8_t telemetryFrame[TelemetryProtocol::MAX_FRAME_SIZE];
static uint16_t telemetrySequence = 0;

// The configured period is retained when switching between NORMAL and LOW.
static uint16_t samplePeriodMs = DEFAULT_SAMPLE_PERIOD_MS;
static bool streamingEnabled = true;
static bool lowPowerMode = false;

static float readTemperatureC()
{
    // Convert the 10-bit ADC reading to voltage, then apply the TMP36
    // offset and scale to obtain temperature in degrees Celsius.
    const int rawAdc = analogRead(TMP36_PIN);

    const float voltage =
        rawAdc * (ADC_REFERENCE_VOLTAGE / 1023.0f);

    return (voltage - TMP36_OFFSET_VOLTAGE)
           / TMP36_VOLTS_PER_C;
}

static uint16_t getEffectiveSamplePeriodMs()
{
    // LOW mode overrides the configured interval without changing it.
    return lowPowerMode
        ? LOW_POWER_SAMPLE_PERIOD_MS
        : samplePeriodMs;
}

static void processCommand(char *command)
{
    // RATE accepts an integer interval in milliseconds within the
    // supported range. Reject missing, malformed, or out-of-range values.
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
        // Sampling continues while streaming is disabled; only telemetry
        // transmission is suppressed.
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
        // Report the configured interval, streaming state, and power mode.
        // The effective interval in LOW mode is reported separately by
        // POWER_STATUS handling on the host, where supported.
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
        // Ignore empty commands, but report non-empty unrecognized input.
        Serial.println("ERR,UNKNOWN_COMMAND");
    }
}

static void processSerialCommands()
{
    // Keep parser state between task iterations so commands can arrive
    // in multiple serial reads. Overlong commands are discarded through
    // the next newline to prevent their remainder being treated as a
    // separate command.
    static char commandBuffer[COMMAND_BUFFER_SIZE];
    static uint8_t commandLength = 0;
    static bool discardingOverlongCommand = false;

    while (Serial.available() > 0)
    {
        char incoming = static_cast<char>(Serial.read());

        // Accept CRLF and LF line endings.
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

            // Null-terminate the command before comparing its contents.
            commandBuffer[commandLength] = '\0';
            processCommand(commandBuffer);
            commandLength = 0;
            continue;
        }

        if (discardingOverlongCommand)
        {
            continue;
        }

        // Reserve one byte for the terminating null character.
        if (commandLength < COMMAND_BUFFER_SIZE - 1)
        {
            commandBuffer[commandLength++] = incoming;
        }
        else
        {
            commandLength = 0;
            discardingOverlongCommand = true;
        }
    }
}

static void sensorTask(void *pvParameters)
{
    // This task does not use a task parameter.
    (void)pvParameters;

    pinMode(LED_PIN, OUTPUT);

    // Use RTOS ticks for elapsed-time scheduling rather than blocking
    // for the full sampling interval, so serial commands remain responsive.
    TickType_t lastSampleTick = xTaskGetTickCount();

    for (;;)
    {
        // Process pending commands frequently, including while telemetry
        // streaming is disabled.
        processSerialCommands();

        TickType_t now = xTaskGetTickCount();
        TickType_t periodTicks =
            pdMS_TO_TICKS(getEffectiveSamplePeriodMs());

        // Ensure a nonzero interval even if the RTOS tick rate is low.
        if (periodTicks == 0)
        {
            periodTicks = 1;
        }

        if (static_cast<TickType_t>(now - lastSampleTick) >=
            periodTicks)
        {
            // Schedule the next interval from the current tick.
            lastSampleTick = now;

            latestReading.timestamp_ms =
                static_cast<uint32_t>(millis());

            latestReading.temperature_c = readTemperatureC();

            if (streamingEnabled)
            {
                // Encode the sequence number, device timestamp, and
                // temperature into the protocol-defined binary frame,
                // including its synchronization fields and CRC.
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
                    // Write the encoded frame as binary bytes. Do not use
                    // Serial.print(), which would convert data to text.
                    Serial.write(
                        telemetryFrame,
                        sizeof(telemetryFrame));

                    // Advance only after successful frame encoding.
                    // The uint16_t sequence wraps naturally at its limit.
                    ++telemetrySequence;
                }
            }

            // Blink the built-in LED during NORMAL mode as a simple
            // activity indicator. LOW mode suppresses this LED activity.
            if (!lowPowerMode)
            {
                digitalWrite(LED_PIN, !digitalRead(LED_PIN));
            }
        }

        // Yield the CPU to other RTOS tasks and check commands again soon.
        vTaskDelay(pdMS_TO_TICKS(10));
    }
}

void setup()
{
    Serial.begin(115200);

    // Create the sensor/telemetry task. A failed task creation is treated
    // as a configuration failure rather than silently running without it.
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
    // Application work is performed by sensorTask under FreeRTOS.
}
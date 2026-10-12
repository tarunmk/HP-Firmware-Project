#ifndef TELEMETRY_PROTOCOL_H
#define TELEMETRY_PROTOCOL_H

#include <Arduino.h>
#include <stdint.h>

namespace TelemetryProtocol
{
    constexpr uint8_t SYNC_BYTE_1 = 0xAA;
    constexpr uint8_t SYNC_BYTE_2 = 0x55;

    constexpr uint8_t MESSAGE_TYPE_TELEMETRY = 0x01;

    constexpr uint8_t TELEMETRY_PAYLOAD_SIZE = 12;
    constexpr uint8_t FRAME_OVERHEAD_SIZE = 8;
    constexpr uint8_t MAX_FRAME_SIZE =
        FRAME_OVERHEAD_SIZE + TELEMETRY_PAYLOAD_SIZE;

    constexpr uint16_t CRC_INITIAL_VALUE = 0xFFFF;
    constexpr uint16_t CRC_POLYNOMIAL = 0x1021;

    inline uint16_t calculateCrc16(
        const uint8_t *data,
        uint8_t length)
    {
        uint16_t crc = CRC_INITIAL_VALUE;

        for (uint8_t i = 0; i < length; ++i)
        {
            crc ^= static_cast<uint16_t>(data[i]) << 8;

            for (uint8_t bit = 0; bit < 8; ++bit)
            {
                if ((crc & 0x8000U) != 0U)
                {
                    crc = static_cast<uint16_t>(
                        (crc << 1) ^ CRC_POLYNOMIAL);
                }
                else
                {
                    crc = static_cast<uint16_t>(crc << 1);
                }
            }
        }

        return crc;
    }

    inline void writeUint16LE(
        uint8_t *destination,
        uint16_t value)
    {
        destination[0] = static_cast<uint8_t>(value);
        destination[1] = static_cast<uint8_t>(value >> 8);
    }

    inline void writeUint32LE(
        uint8_t *destination,
        uint32_t value)
    {
        for (uint8_t i = 0; i < 4; ++i)
        {
            destination[i] = static_cast<uint8_t>(
                value >> (8U * i));
        }
    }

    inline void writeUint64LE(
        uint8_t *destination,
        uint64_t value)
    {
        for (uint8_t i = 0; i < 8; ++i)
        {
            destination[i] = static_cast<uint8_t>(
                value >> (8U * i));
        }
    }

    inline bool encodeTelemetry(
        uint8_t *frame,
        uint8_t capacity,
        uint16_t sequence,
        uint64_t timestampMs,
        float temperatureC)
    {
        if (frame == nullptr || capacity < MAX_FRAME_SIZE)
        {
            return false;
        }

        frame[0] = SYNC_BYTE_1;
        frame[1] = SYNC_BYTE_2;
        frame[2] = MESSAGE_TYPE_TELEMETRY;
        frame[3] = TELEMETRY_PAYLOAD_SIZE;

        writeUint16LE(&frame[4], sequence);
        writeUint64LE(&frame[6], timestampMs);

        union FloatBytes
        {
            float value;
            uint8_t bytes[sizeof(float)];
        };

        static_assert(sizeof(float) == 4,
                      "Protocol requires 32-bit float");

        FloatBytes temperature;
        temperature.value = temperatureC;

        for (uint8_t i = 0; i < 4; ++i)
        {
            frame[14 + i] = temperature.bytes[i];
        }

        const uint16_t crc = calculateCrc16(
            &frame[2],
            4 + TELEMETRY_PAYLOAD_SIZE);

        writeUint16LE(&frame[18], crc);

        return true;
    }
}

#endif
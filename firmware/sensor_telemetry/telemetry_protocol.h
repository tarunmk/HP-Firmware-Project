
#ifndef TELEMETRY_PROTOCOL_H
#define TELEMETRY_PROTOCOL_H

#include <Arduino.h>
#include <stdint.h>

namespace TelemetryProtocol
{
    // Frame synchronization bytes help the host identify the beginning
    // of a telemetry frame in the serial byte stream.
    constexpr uint8_t SYNC_BYTE_1 = 0xAA;
    constexpr uint8_t SYNC_BYTE_2 = 0x55;

    // Identifies this frame as a telemetry message.
    constexpr uint8_t MESSAGE_TYPE_TELEMETRY = 0x01;

    // Payload: 2-byte sequence number, 8-byte timestamp, and 4-byte
    // IEEE-754 temperature value. The frame overhead includes the
    // sync bytes, message type, length field, and 2-byte CRC.
    constexpr uint8_t TELEMETRY_PAYLOAD_SIZE = 12;
    constexpr uint8_t FRAME_OVERHEAD_SIZE = 8;
    constexpr uint8_t MAX_FRAME_SIZE =
        FRAME_OVERHEAD_SIZE + TELEMETRY_PAYLOAD_SIZE;

    // CRC-16/CCITT-FALSE parameters. The CRC covers the message type,
    // payload length, and payload, but excludes the sync bytes.
    constexpr uint16_t CRC_INITIAL_VALUE = 0xFFFF;
    constexpr uint16_t CRC_POLYNOMIAL = 0x1021;

    inline uint16_t calculateCrc16(
        const uint8_t *data,
        uint8_t length)
    {
        uint16_t crc = CRC_INITIAL_VALUE;

        // Process each input byte, most-significant bit first.
        for (uint8_t i = 0; i < length; ++i)
        {
            crc ^= static_cast<uint16_t>(data[i]) << 8;

            for (uint8_t bit = 0; bit < 8; ++bit)
            {
                // Apply the polynomial when the current top bit is set.
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

    // Serialize a 16-bit unsigned integer in little-endian order:
    // least-significant byte first.
    inline void writeUint16LE(
        uint8_t *destination,
        uint16_t value)
    {
        destination[0] = static_cast<uint8_t>(value);
        destination[1] = static_cast<uint8_t>(value >> 8);
    }

    // Serialize a 32-bit unsigned integer in little-endian order.
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

    // Serialize a 64-bit unsigned integer in little-endian order.
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
        // Ensure the destination exists and can hold the entire frame.
        if (frame == nullptr || capacity < MAX_FRAME_SIZE)
        {
            return false;
        }

        // Frame bytes 0–3: synchronization marker, message type,
        // and payload length.
        frame[0] = SYNC_BYTE_1;
        frame[1] = SYNC_BYTE_2;
        frame[2] = MESSAGE_TYPE_TELEMETRY;
        frame[3] = TELEMETRY_PAYLOAD_SIZE;

        // Frame bytes 4–5: sequence number.
        writeUint16LE(&frame[4], sequence);

        // Frame bytes 6–13: device timestamp in milliseconds.
        writeUint64LE(&frame[6], timestampMs);

        // The protocol transmits temperature as a 4-byte floating-point
        // value. Both host and firmware must agree on its representation
        // and byte order.
        union FloatBytes
        {
            float value;
            uint8_t bytes[sizeof(float)];
        };

        static_assert(sizeof(float) == 4,
                      "Protocol requires 32-bit float");

        FloatBytes temperature;
        temperature.value = temperatureC;

        // Frame bytes 14–17: temperature bytes.
        // This copies the MCU's native float representation; the target
        // and host implementation must use compatible IEEE-754 encoding
        // and little-endian byte order.
        for (uint8_t i = 0; i < 4; ++i)
        {
            frame[14 + i] = temperature.bytes[i];
        }

        // Calculate the CRC over bytes 2–17: message type, payload
        // length, sequence number, timestamp, and temperature.
        const uint16_t crc = calculateCrc16(
            &frame[2],
            4 + TELEMETRY_PAYLOAD_SIZE);

        // Frame bytes 18–19: CRC stored in little-endian order.
        writeUint16LE(&frame[18], crc);

        return true;
    }
}

#endif

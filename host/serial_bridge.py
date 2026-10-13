
import argparse
import socket
import threading
import serial


def main():
    # Configure the physical serial connection and local TCP endpoint.
    parser = argparse.ArgumentParser(
        description="Keep the Arduino serial port open and relay bytes."
    )
    parser.add_argument("--port", required=True)
    parser.add_argument("--baud", type=int, default=115200)
    parser.add_argument("--socket-host", default="127.0.0.1")
    parser.add_argument("--socket-port", type=int, default=8765)
    args = parser.parse_args()

    # Coordinate shutdown and shared access to connected clients.
    stop_event = threading.Event()
    clients = set()
    clients_lock = threading.Lock()

    # Prevent concurrent dashboard writes from interleaving on the serial port.
    serial_write_lock = threading.Lock()

    def remove_client(client):
        # Remove the client from the shared set before closing its socket.
        with clients_lock:
            clients.discard(client)

        # Shutdown and close may fail if the peer has already disconnected.
        try:
            client.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass

        try:
            client.close()
        except OSError:
            pass

    def broadcast(data):
        # Copy the client set under the lock, then release it before network I/O.
        # This avoids holding the shared lock during potentially blocking sends.
        with clients_lock:
            active_clients = list(clients)

        # Forward incoming serial bytes without modifying the binary stream.
        for client in active_clients:
            try:
                client.sendall(data)
            except OSError:
                # A failed send usually indicates a disconnected or unusable client.
                remove_client(client)

    def serial_reader(connection):
        # Continuously read from the board independently of dashboard activity.
        # Keeping this connection open avoids reopening the serial port every
        # time the dashboard exits and reconnects.
        while not stop_event.is_set():
            try:
                data = connection.read(256)
                if data:
                    broadcast(data)
            except (serial.SerialException, OSError) as error:
                if not stop_event.is_set():
                    print(f"Serial read error: {error}")
                    stop_event.set()
                break

    def handle_client(client, connection):
        # Relay commands from the dashboard to the board until either side
        # disconnects or the bridge begins shutting down.
        try:
            while not stop_event.is_set():
                try:
                    data = client.recv(256)
                except socket.timeout:
                    # Periodically recheck stop_event instead of blocking forever.
                    continue

                if not data:
                    # An empty read indicates that the client closed its connection.
                    break

                try:
                    # Serialize writes so command bytes from different callers
                    # cannot be written concurrently to the physical serial port.
                    with serial_write_lock:
                        connection.write(data)
                except (serial.SerialException, OSError) as error:
                    if not stop_event.is_set():
                        print(f"Serial write error: {error}")
                        stop_event.set()
                    break

        except OSError:
            # The dashboard disconnected or its socket encountered an error.
            pass
        finally:
            remove_client(client)

    server = None
    reader = None

    try:
        # Open the physical port once and keep it open for the bridge lifetime.
        # The timeout allows the reader thread to periodically check for shutdown.
        # These settings disable hardware flow control; they do not guarantee that
        # every board or USB interface will avoid resetting when the port opens.
        with serial.Serial(
            args.port,
            args.baud,
            timeout=0.1,
            write_timeout=1.0,
            dsrdtr=False,
            rtscts=False,
        ) as connection:
            print(f"Serial connected: {args.port} at {args.baud}")

            # Create the TCP server used by the host dashboard.
            server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            server.bind((args.socket_host, args.socket_port))
            server.listen()

            # A timeout lets the accept loop periodically check stop_event.
            server.settimeout(0.5)

            print(
                f"Bridge listening on "
                f"{args.socket_host}:{args.socket_port}"
            )

            # A dedicated reader keeps consuming serial data even when no
            # dashboard client is connected.
            reader = threading.Thread(
                target=serial_reader,
                args=(connection,),
                name="serial-reader",
                daemon=True,
            )
            reader.start()

            # Accept dashboard connections while the bridge is running.
            while not stop_event.is_set():
                try:
                    client, address = server.accept()
                except socket.timeout:
                    continue

                except OSError:
                    if not stop_event.is_set():
                        raise
                    break

                # Periodic receive timeouts allow the client handler to stop promptly.
                client.settimeout(0.5)

                # Support only one dashboard client at a time. This avoids
                # multiple clients issuing conflicting commands to the same board.
                with clients_lock:
                    if clients:
                        reject_client = True
                    else:
                        clients.add(client)
                        reject_client = False

                if reject_client:
                    print(f"Rejected additional dashboard client: {address}")
                    client.close()
                    continue

                print(f"Dashboard connected: {address}")

                # Handle dashboard-to-serial traffic independently of the
                # serial reader so incoming telemetry can continue concurrently.
                threading.Thread(
                    target=handle_client,
                    args=(client, connection),
                    name="dashboard-client",
                    daemon=True,
                ).start()

    except KeyboardInterrupt:
        print("\nShutting down serial bridge...")

    except (serial.SerialException, OSError) as error:
        print(f"Bridge error: {error}")
        raise SystemExit(1)

    finally:
        # Signal worker threads to stop before releasing shared resources.
        stop_event.set()

        if server is not None:
            try:
                server.close()
            except OSError:
                pass

        # Close any dashboard sockets that remain connected.
        with clients_lock:
            remaining_clients = list(clients)

        for client in remaining_clients:
            remove_client(client)

        # Give the serial reader a chance to exit cleanly.
        if reader is not None:
            reader.join(timeout=1.0)

        print("Serial bridge stopped.")


if __name__ == "__main__":
    main()

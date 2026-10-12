
import argparse
import socket
import threading

import serial


def main():
    parser = argparse.ArgumentParser(
        description="Keep the Arduino serial port open and relay bytes."
    )
    parser.add_argument("--port", required=True)
    parser.add_argument("--baud", type=int, default=115200)
    parser.add_argument("--socket-host", default="127.0.0.1")
    parser.add_argument("--socket-port", type=int, default=8765)
    args = parser.parse_args()

    stop_event = threading.Event()
    clients = set()
    clients_lock = threading.Lock()
    serial_write_lock = threading.Lock()

    def remove_client(client):
        with clients_lock:
            clients.discard(client)

        try:
            client.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass

        try:
            client.close()
        except OSError:
            pass

    def broadcast(data):
        # Never hold the shared lock during potentially blocking network I/O.
        with clients_lock:
            active_clients = list(clients)

        for client in active_clients:
            try:
                client.sendall(data)
            except OSError:
                remove_client(client)

    def serial_reader(connection):
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
        try:
            while not stop_event.is_set():
                try:
                    data = client.recv(256)
                except socket.timeout:
                    continue

                if not data:
                    break

                try:
                    with serial_write_lock:
                        connection.write(data)
                except (serial.SerialException, OSError) as error:
                    if not stop_event.is_set():
                        print(f"Serial write error: {error}")
                        stop_event.set()
                    break

        except OSError:
            # The dashboard disconnected or its socket failed.
            pass
        finally:
            remove_client(client)

    server = None
    reader = None

    try:
        with serial.Serial(
            args.port,
            args.baud,
            timeout=0.1,
            write_timeout=1.0,
            dsrdtr=False,
            rtscts=False,
        ) as connection:
            print(f"Serial connected: {args.port} at {args.baud}")

            server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            server.bind((args.socket_host, args.socket_port))
            server.listen()
            server.settimeout(0.5)

            print(
                f"Bridge listening on "
                f"{args.socket_host}:{args.socket_port}"
            )

            reader = threading.Thread(
                target=serial_reader,
                args=(connection,),
                name="serial-reader",
                daemon=True,
            )
            reader.start()

            while not stop_event.is_set():
                try:
                    client, address = server.accept()
                except socket.timeout:
                    continue

                except OSError:
                    if not stop_event.is_set():
                        raise
                    break


                client.settimeout(0.5)

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
        stop_event.set()

        if server is not None:
            try:
                server.close()
            except OSError:
                pass

        with clients_lock:
            remaining_clients = list(clients)

        for client in remaining_clients:
            remove_client(client)

        if reader is not None:
            reader.join(timeout=1.0)

        print("Serial bridge stopped.")


if __name__ == "__main__":
    main()
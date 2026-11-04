def detect_inverter_logger():
    import os
    import socket

    from dotenv import load_dotenv

    load_dotenv()

    DEVICE_LAN_IP = os.getenv("DEVICE_LAN_IP")
    BROADCAST = os.getenv("BROADCAST")

    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.setsockopt(
        socket.SOL_SOCKET,
        socket.SO_BROADCAST,
        1,
    )
    s.bind((DEVICE_LAN_IP, 0))
    s.settimeout(3)
    s.sendto(b"WIFIKIT-214028-READ", (BROADCAST, 48899))
    try:
        while True:
            data, _ = s.recvfrom(1024)
            print(data.decode())
    except socket.timeout:
        print("no more replies")


if __name__ == "__main__":
    detect_inverter_logger()

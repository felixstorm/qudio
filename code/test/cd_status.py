import fcntl
import os

CDROM_DRIVE = '/dev/sr0'

def detect_tray(cdrom_device):
    """detect_tray reads status of the CDROM_DRIVE.
    Statuses:
    1 = no disk in tray
    2 = tray open
    3 = reading tray
    4 = disk in tray
    """
    fd = os.open(cdrom_device, os.O_RDONLY | os.O_NONBLOCK)
    rv = fcntl.ioctl(fd, 0x5326)
    os.close(fd)
    print(rv)

detect_tray(CDROM_DRIVE)

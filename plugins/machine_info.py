from datetime import datetime, timezone
import platform
import sys
import time


class Plugin:
    def __init__(self):
        self.name = "Machine infomation"
        self.version = 'v1.0'
        self.author = 'Stevesuk0 <stevesukawa@outlook.com>'

        self.export_function = {
            "Get system infomation": self.get_client_system,
            "Get current time": self.get_current_time,
        }

    def get_client_system(self):
        """
        Get the user's client device operating system and version information.
        """
        return {
            "os": platform.system(),
            "version": platform.version(),
            "release": platform.release(),
            "architecture": platform.machine(),
            "python_version": sys.version.split()[0],
        }

    def get_current_time(self):
        """
        Get the user's client device time.
        """

        local_time = datetime.now().astimezone()

        return {
            "local_time": local_time.strftime("%Y-%m-%d %H:%M:%S"),
            "raw": local_time.isoformat(),
            "timestamp": int(local_time.timestamp()),
            "timestamp_ms": int(local_time.timestamp() * 1000),
            "utc": datetime.now(timezone.utc).isoformat(),
            "utc_offset": local_time.strftime("%z"),
            "timezone": str(local_time.tzinfo),
            "epoch": time.time(),
        }

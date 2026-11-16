"""CPU, RAM, GPU (NVIDIA via NVML), network and disk usage."""
import logging
import os
import time

import psutil

from .text import ascii_fold

log = logging.getLogger(__name__)


def _cpu_name() -> str:
    try:
        import winreg

        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,
                            r"HARDWARE\DESCRIPTION\System\CentralProcessor\0") as k:
            name = winreg.QueryValueEx(k, "ProcessorNameString")[0]
    except OSError:
        import platform

        name = platform.processor()
    for junk in ("(R)", "(TM)", "CPU", "Processor"):
        name = name.replace(junk, "")
    name = name.split("@")[0]
    return ascii_fold(name, 40)


class Stats:
    def __init__(self):
        psutil.cpu_percent(None)
        self._net = psutil.net_io_counters()
        self._t = time.monotonic()
        self._cpu_name = _cpu_name()
        self._drive = os.environ.get("SystemDrive", "C:") + "\\"
        self._gpu = None
        self._gpu_name = ""
        try:
            import pynvml

            pynvml.nvmlInit()
            self._nvml = pynvml
            self._gpu = pynvml.nvmlDeviceGetHandleByIndex(0)
            name = pynvml.nvmlDeviceGetName(self._gpu)
            if isinstance(name, bytes):
                name = name.decode()
            self._gpu_name = ascii_fold(name.replace("NVIDIA ", ""), 40)
        except Exception as e:  # no NVIDIA GPU or driver
            log.info("GPU stats unavailable: %s", e)

    def sample(self) -> dict:
        now = time.monotonic()
        net = psutil.net_io_counters()
        dt = max(now - self._t, 0.001)
        down = (net.bytes_recv - self._net.bytes_recv) / dt / 1024
        up = (net.bytes_sent - self._net.bytes_sent) / dt / 1024
        self._net, self._t = net, now

        vm = psutil.virtual_memory()
        msg = {
            "type": "stats",
            "cpu": round(psutil.cpu_percent(None), 1),
            "ram_used": round(vm.used / 2**30, 2),
            "ram_total": round(vm.total / 2**30, 1),
            "net_down": round(down, 1),
            "net_up": round(up, 1),
            "disk": round(psutil.disk_usage(self._drive).percent, 1),
            "cpu_name": self._cpu_name,
            "gpu_name": self._gpu_name,
        }
        if self._gpu is not None:
            n = self._nvml
            try:
                mem = n.nvmlDeviceGetMemoryInfo(self._gpu)
                msg["gpu"] = n.nvmlDeviceGetUtilizationRates(self._gpu).gpu
                msg["gpu_temp"] = n.nvmlDeviceGetTemperature(self._gpu, n.NVML_TEMPERATURE_GPU)
                msg["vram_used"] = round(mem.used / 2**30, 2)
                msg["vram_total"] = round(mem.total / 2**30, 1)
            except Exception as e:
                log.debug("nvml read failed: %s", e)
        return msg

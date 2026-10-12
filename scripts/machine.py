import os
import platform
import re
import subprocess


def _run(args: list[str]) -> str | None:
    try:
        done = subprocess.run(args, capture_output=True, text=True, timeout=30, check=True)
    except (OSError, subprocess.SubprocessError):
        return None
    return done.stdout.strip() or None


def parse_cpuinfo(text: str) -> str | None:
    m = re.search(r"^model name\s*:\s*(.+)$", text, re.M)
    return m.group(1).strip() if m else None


def parse_meminfo_gib(text: str) -> float | None:
    m = re.search(r"^MemTotal:\s*(\d+) kB", text, re.M)
    return round(int(m.group(1)) / 2**20, 1) if m else None


def _powershell(expr: str) -> str | None:
    return _run(["powershell", "-NoProfile", "-Command", expr])


def cpu_model() -> str | None:
    system = platform.system()
    if system == "Windows":
        return _powershell("(Get-CimInstance Win32_Processor | Select-Object -First 1).Name")
    if system == "Darwin":
        return _run(["sysctl", "-n", "machdep.cpu.brand_string"])
    try:
        with open("/proc/cpuinfo", encoding="utf-8") as f:
            return parse_cpuinfo(f.read())
    except OSError:
        return None


def memory_gib() -> float | None:
    system = platform.system()
    if system == "Windows":
        raw = _powershell("(Get-CimInstance Win32_ComputerSystem).TotalPhysicalMemory")
        return round(int(raw) / 2**30, 1) if raw and raw.isdigit() else None
    if system == "Darwin":
        raw = _run(["sysctl", "-n", "hw.memsize"])
        return round(int(raw) / 2**30, 1) if raw and raw.isdigit() else None
    try:
        with open("/proc/meminfo", encoding="utf-8") as f:
            return parse_meminfo_gib(f.read())
    except OSError:
        return None


def describe() -> dict:
    return {
        "os": f"{platform.system()} {platform.release()} {platform.machine()}",
        "cpu": cpu_model(),
        "logical_cpus": os.cpu_count(),
        "memory_gib": memory_gib(),
        "python": platform.python_version(),
    }

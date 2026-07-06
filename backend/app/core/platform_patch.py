import os
import platform
import sys
from types import SimpleNamespace


def patch_windows_platform_machine() -> None:
    if not sys.platform.startswith("win"):
        return
    if os.environ.get("MAIL_GMAIL_DISABLE_PLATFORM_PATCH") == "1":
        return

    machine = os.environ.get("PROCESSOR_ARCHITECTURE") or "AMD64"
    processor = os.environ.get("PROCESSOR_IDENTIFIER") or machine
    node = os.environ.get("COMPUTERNAME") or ""

    def safe_uname():
        return SimpleNamespace(
            system="Windows",
            node=node,
            release="",
            version="",
            machine=machine,
            processor=processor,
        )

    platform.uname = safe_uname
    platform.machine = lambda: machine


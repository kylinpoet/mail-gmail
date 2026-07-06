try:
    from app.core.platform_patch import patch_windows_platform_machine

    patch_windows_platform_machine()
except Exception:
    pass


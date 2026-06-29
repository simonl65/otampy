try:
    import uos as _os
except ImportError:
    import os as _os


def run(core, callback=None):
    """
    Check if the update request flag file exists, execute the callback to
    perform the update, and remove the flag file.
    """
    core.logger.debug("Checking for update request flag file...")
    flag = core.config.get("UPDATE_REQUEST_FLAG_FILE")

    if not flag:
        core.logger.error("Missing filename for update request flag file")
        return

    # Check if the flag file exists
    has_flag = False
    try:
        _os.stat(flag)
        has_flag = True
    except OSError:
        pass

    if has_flag:
        core.logger.debug(f"Update request flag found: {flag}")
        core.transport.send(b"READY")

        if callback is not None:
            # Handle variable argument callback cleanly
            try:
                callback(flag)
            except TypeError:
                callback()

        # Remove the flag file
        try:
            _os.remove(flag)
        except OSError:
            try:
                getattr(_os, "unlink", lambda _p: None)(flag)
            except Exception:
                core.logger.debug(f"Could not remove update flag: {flag}")

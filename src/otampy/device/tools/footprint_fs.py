"""Read-only on-device filesystem inventory for footprint review FP-02.

Run with ``mpremote ... run packages/device/tools/footprint_fs.py``. The probe
is not copied by ``otampy deploy``.
"""


def _join(parent, name):
    if parent == "/":
        return "/" + name
    return parent + "/" + name


def _walk(os, path, block_size):
    file_count = 0
    directory_count = 0
    logical_bytes = 0
    rounded_file_bytes = 0

    names = os.listdir(path)
    names.sort()
    for name in names:
        child = _join(path, name)
        stat = os.stat(child)
        if stat[0] & 0x4000:
            print(f"OTAMPY_DIR|{child}")
            directory_count += 1
            child_totals = _walk(os, child, block_size)
            file_count += child_totals[0]
            directory_count += child_totals[1]
            logical_bytes += child_totals[2]
            rounded_file_bytes += child_totals[3]
        else:
            size = stat[6]
            rounded = ((size + block_size - 1) // block_size) * block_size
            print(f"OTAMPY_FILE|{child}|{size}|{rounded}")
            file_count += 1
            logical_bytes += size
            rounded_file_bytes += rounded

    return file_count, directory_count, logical_bytes, rounded_file_bytes


def main():
    import os

    statvfs = os.statvfs("/")
    block_size = statvfs[0]
    fragment_size = statvfs[1]
    total_bytes = block_size * statvfs[2]
    free_bytes = block_size * statvfs[3]
    available_bytes = block_size * statvfs[4]
    used_bytes = total_bytes - free_bytes

    print(
        f"OTAMPY_STATVFS|{block_size}|{fragment_size}|{statvfs[2]}|"
        f"{statvfs[3]}|{statvfs[4]}|{total_bytes}|{free_bytes}|"
        f"{available_bytes}|{used_bytes}"
    )

    totals = _walk(os, "/", block_size)
    metadata_bytes = used_bytes - totals[3]
    print(
        f"OTAMPY_FS_TOTAL|{totals[0]}|{totals[1]}|{totals[2]}|"
        f"{totals[3]}|{metadata_bytes}"
    )


main()

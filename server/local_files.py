import os
import re
import stat
from pathlib import Path, PureWindowsPath


MAX_FILE_BYTES = 512 * 1024


def is_local_absolute(value, windows):
    if not isinstance(value, str) or "\x00" in value:
        return False
    if windows:
        return bool(re.fullmatch(r"[A-Za-z]:[\\/][^:]+", value)) and not any(
            PureWindowsPath(part).is_reserved() for part in PureWindowsPath(value).parts[1:]
        )
    return value.startswith("/") and not value.startswith("//")


def read_shared_file(value):
    if isinstance(value, str):
        value = value.strip()
        if value.startswith('"') and value.endswith('"'):
            value = value[1:-1]
        if os.name != "nt" and value.startswith("~/"):
            value = os.path.expanduser(value)
    windows = os.name == "nt"
    if not is_local_absolute(value, windows):
        example = r"C:\project\main.py" if windows else "/path/to/project/main.py"
        raise ValueError(f"Enter an absolute local file path, such as {example}.")
    try:
        path = Path(value).resolve(strict=True)
        if not is_local_absolute(str(path), windows) or not path.is_file():
            raise ValueError("Choose a regular local file.")
        with open(path, "rb", opener=lambda name, flags: os.open(name, flags | getattr(os, "O_NONBLOCK", 0))) as file:
            if not stat.S_ISREG(os.fstat(file.fileno()).st_mode):
                raise ValueError("Choose a regular local file.")
            data = file.read(MAX_FILE_BYTES + 1)
    except (OSError, RuntimeError) as error:
        raise ValueError("Could not open that file. Check the path and permissions.") from error
    if len(data) > MAX_FILE_BYTES:
        raise ValueError("Choose a text file up to 512 KiB, or paste a relevant excerpt.")
    try:
        text = data.decode("utf-16" if data.startswith((b"\xff\xfe", b"\xfe\xff")) else "utf-8-sig")
    except UnicodeDecodeError as error:
        raise ValueError("Choose a UTF-8 or UTF-16 text file.") from error
    if not text.strip() or "\x00" in text:
        raise ValueError("Choose a non-empty text or source file.")
    return {"name": path.name, "text": text}


def validate_excerpts(items):
    if not isinstance(items, list) or len(items) > 6:
        raise ValueError("Share at most six file excerpts.")
    for item in items:
        if (
            not isinstance(item, dict) or not isinstance(item.get("name"), str)
            or not 1 <= len(item["name"]) <= 260
            or not isinstance(item.get("text"), str) or not 1 <= len(item["text"]) <= 1800
            or type(item.get("line")) is not int or not 1 <= item["line"] <= MAX_FILE_BYTES
            or "\x00" in item["text"]
        ):
            raise ValueError("Invalid local file excerpt.")
    return items

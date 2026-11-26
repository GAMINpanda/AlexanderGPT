import re
from pathlib import Path, PureWindowsPath


MAX_FILE_BYTES = 512 * 1024


def read_shared_file(value):
    if isinstance(value, str):
        value = value.strip()
        if value.startswith('"') and value.endswith('"'):
            value = value[1:-1]
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z]:[\\/][^:\x00]+", value):
        raise ValueError("Enter an absolute local file path, such as C:\\project\\main.py.")
    if any(PureWindowsPath(part).is_reserved() for part in PureWindowsPath(value).parts[1:]):
        raise ValueError("Choose a regular local file.")
    try:
        path = Path(value).resolve(strict=True)
        if not re.fullmatch(r"[A-Za-z]:[\\/][^:\x00]+", str(path)) or not path.is_file():
            raise ValueError("Choose a regular local file.")
        with path.open("rb") as file:
            data = file.read(MAX_FILE_BYTES + 1)
    except OSError as error:
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

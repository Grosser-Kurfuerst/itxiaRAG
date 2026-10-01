import json
import os
from pathlib import Path

from django.contrib.auth import get_user_model
from django.core.management.base import CommandError

from contracts.errors import DomainError


def actor_by_name(name):
    try:
        return get_user_model().objects.get(username=name, is_active=True)
    except get_user_model().DoesNotExist:
        raise DomainError("PERMISSION_DENIED", "账号不存在或已停用", 403) from None


def read_text(path):
    with Path(path).open("rb") as stream:
        data = stream.read(131073)
    if len(data) > 131072:
        raise DomainError("INPUT_TOO_LARGE", "文件超过 128 KiB")
    return data.decode("utf-8")


def read_metadata(path):
    try:
        value = json.loads(read_text(path))
    except ValueError:
        raise DomainError("INVALID_ARGUMENT", "metadata 必须为合法 JSON") from None
    if type(value) is not dict or "input_text" in value:
        raise DomainError("INVALID_ARGUMENT", "metadata 须为不含 input_text 的对象")
    return value


def validate_input(serializer_class, data):
    serializer = serializer_class(data=data)
    serializer.is_valid(raise_exception=True)
    return serializer.validated_data


def print_job(command, summary):
    command.stdout.write(json.dumps(summary, ensure_ascii=False, default=str))
    if summary["status"] == "failed" or summary["error_code"]:
        raise CommandError("任务失败或发布冲突", returncode=3)
    if not summary["is_current"]:
        raise CommandError("任务已接收，待人工复核或发布", returncode=4)


def write_report(path, report):
    # 报告含原文，使用独占创建；不覆盖或跟随已有文件／符号链接。
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as stream:
        stream.write("# 导入任务报告\n\n```json\n")
        json.dump(report, stream, ensure_ascii=False, indent=2, default=str)
        stream.write("\n```\n")

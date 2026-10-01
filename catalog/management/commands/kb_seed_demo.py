"""通过正式业务服务创建合成演示资料；重跑保留维护者的后续变更。"""
import json
import re
from pathlib import Path

from catalog.accounts import configure_account
from catalog.management.base import KBCommand
from catalog.management.io import validate_input
from catalog.models import KnowledgeSource
from catalog.presenters import job_summary
from contracts.errors import DomainError
from contracts.serializers import SourceImportSerializer
from ingestion.pipeline import import_text


class Command(KBCommand):
    help = "显式演示环境：创建普通／内部／维护账号和三份合成短笔记"

    def add_arguments(self, parser):
        parser.add_argument("--confirm-demo", action="store_true")
        parser.add_argument("--prefix", default="itxia-demo")
        parser.add_argument("--token-dir", default="/tmp/itxia-demo-tokens")

    def run(self, *args, **options):
        if not options["confirm_demo"]:
            raise DomainError("INVALID_ARGUMENT", "请显式指定 --confirm-demo，仅在演示环境执行")
        prefix = options["prefix"]
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,32}", prefix):
            raise DomainError("INVALID_ARGUMENT", "prefix 仅支持 1–32 位字母数字连字符下划线")
        directory = Path(options["token_dir"])
        directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        users, accounts = {}, []
        roles = {"reader": [], "member": ["read_internal"],
                 "maintainer": ["maintain_source", "review_import", "read_internal"]}
        for role, permissions in roles.items():
            name = prefix + "-" + role
            file = directory / (name + ".token")
            users[role] = configure_account(name, permissions, token_file=file)
            accounts.append({"username": name, "token_file": str(file)})
        sources = []
        for role, visibility, manual in [("public", "public", False), ("internal", "internal", False), ("pending", "public", True)]:
            locator = "manual:" + prefix + "-" + role
            existing = KnowledgeSource.objects.filter(source_type="manual", canonical_locator=locator).first()
            if existing:
                sources.append({"source_id": existing.pk, "canonical_locator": locator,
                                "status": existing.status, "current_build_id": existing.current_build_id,
                                "existing": True})
                continue
            data = validate_input(SourceImportSerializer, {
                "source_type": "manual", "canonical_locator": locator, "visibility": visibility,
                "authorization_status": "confirmed", "authorization_note": "仓库自编合成演示，无真实个人数据",
                "title": {"public": "公开备份笔记", "internal": "内部备份笔记", "pending": "待审备份笔记"}[role],
                "input_text": "维护电脑前应备份重要文件。\n备份后先验证文件能否恢复。",
                "format": "txt", "document_schema": "generic_note", "schema_version": 1,
                "redaction_confirmed": True, "require_manual_review": manual,
            })
            job, reused = import_text(data, users["maintainer"])
            sources.append({**job_summary(job, reused), "canonical_locator": locator, "existing": False})
        self.stdout.write(json.dumps({"accounts": accounts, "sources": sources}, ensure_ascii=False, default=str))

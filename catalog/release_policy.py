"""受版本管理的自动放行资格；清单不改变内容或索引身份。"""
import json
import re
from pathlib import Path

from django.conf import settings
from django.contrib.auth import get_user_model
from rest_framework.authtoken.models import Token

from catalog.hashes import digest
from catalog.policies import SYSTEM_USERNAME
from contracts.errors import DomainError


def validate_policy(value):
    if type(value) is not dict or set(value) != {"schema_version", "entries"}:
        raise ValueError("invalid policy")
    if type(value["schema_version"]) is not int or value["schema_version"] != 1 or type(value["entries"]) is not list:
        raise ValueError("invalid policy version")
    seen = set()
    for entry in value["entries"]:
        expected = {"document_schema", "schema_version", "index_profile_hash", "sample_report", "confirmed_by"}
        if type(entry) is not dict or set(entry) != expected:
            raise ValueError("invalid entry")
        for key in ("document_schema", "index_profile_hash", "sample_report", "confirmed_by"):
            if type(entry[key]) is not str or not entry[key].strip():
                raise ValueError("missing qualification evidence")
        if type(entry["schema_version"]) is not int or entry["schema_version"] < 1:
            raise ValueError("invalid document version")
        if not re.fullmatch(r"[0-9a-f]{64}", entry["index_profile_hash"]):
            raise ValueError("invalid index hash")
        key = (entry["document_schema"], entry["schema_version"], entry["index_profile_hash"])
        if key in seen:
            raise ValueError("duplicate qualification")
        seen.add(key)
    return value


def load_policy():
    try:
        value = json.loads((Path(settings.PROFILE_DIR) / "auto-release.json").read_text(encoding="utf-8"))
        return validate_policy(value)
    except (OSError, ValueError, TypeError):
        raise DomainError("RELEASE_POLICY_UNAVAILABLE", "自动放行清单不可用，请检查部署配置", 503) from None


def qualified(policy, job):
    return any(entry["document_schema"] == job.document_schema
               and entry["schema_version"] == job.schema_version
               and entry["index_profile_hash"] == job.index_profile_hash for entry in policy["entries"])


def review_reasons(policy, job):
    reasons = []
    if job.quality_report["requested_manual_review"]:
        reasons.append("调用方要求人工复核")
    if not qualified(policy, job):
        reasons.append("配置未列入自动放行清单")
    return reasons


def require_auto_qualification(job):
    policy = load_policy()
    if not qualified(policy, job) or job.quality_report.get("requested_manual_review"):
        raise DomainError("AUTO_RELEASE_NOT_QUALIFIED", "自动放行资格已失效，不能发布", 409)
    return digest(policy)


def system_actor():
    user = get_user_model().objects.filter(username=SYSTEM_USERNAME).first()
    expected = {"catalog.read_internal", "catalog.maintain_source", "catalog.review_import"}
    if (user is None or not user.is_active or user.is_staff or user.is_superuser
            or user.has_usable_password() or user.get_all_permissions() != expected
            or Token.objects.filter(user=user).exists()):
        raise DomainError("SYSTEM_ACCOUNT_UNAVAILABLE", "系统审计账号不可用，请运行受控初始化", 503)
    return user

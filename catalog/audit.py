import json

from django.contrib.admin.models import CHANGE, LogEntry
from django.contrib.contenttypes.models import ContentType


def record(actor, obj, action, **changes):
    """由调用服务放在状态变更的事务内；调用者只传 ID/状态/安全原因。"""
    return LogEntry.objects.create(
        user=actor, content_type=ContentType.objects.get_for_model(obj),
        object_id=str(obj.pk), object_repr=f"{obj._meta.model_name}:{obj.pk}",
        action_flag=CHANGE,
        change_message=json.dumps({"action": action, **changes}, ensure_ascii=False, default=str),
    )

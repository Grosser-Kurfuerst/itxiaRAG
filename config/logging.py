import json
import logging
from datetime import datetime, timezone


class SafeJSONFormatter(logging.Formatter):
    """只记录显式元数据，避免异常、SQL 参数和请求正文进入日志。"""

    def format(self, record):
        data = {"time": datetime.now(timezone.utc).isoformat(),
                "level": record.levelname, "logger": record.name,
                "event": getattr(record, "event", "application_event")}
        for key in ("request_id", "query_id", "actor_id", "source_id", "job_id",
                    "error_code", "error_class", "duration_ms", "status"):
            if hasattr(record, key):
                data[key] = getattr(record, key)
        return json.dumps(data, ensure_ascii=False, default=str)

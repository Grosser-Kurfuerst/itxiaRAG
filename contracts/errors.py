class DomainError(Exception):
    def __init__(self, code, message, status=400):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status


class SourceAccessError(Exception):
    """凭据或权限导致整批无法继续；与单篇 DomainError 分开，防止被导入服务逐篇吞掉。"""

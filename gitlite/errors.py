class GitLiteError(Exception):
    """An expected user-facing GitLite failure."""


class RepositoryError(GitLiteError):
    pass


class UsageError(GitLiteError):
    pass


class CorruptionError(RepositoryError):
    pass


class PathError(RepositoryError):
    pass


class LockError(RepositoryError):
    pass


class ConflictError(RepositoryError):
    pass


class RecoveryError(RepositoryError):
    pass

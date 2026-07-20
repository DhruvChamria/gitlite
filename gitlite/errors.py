class GitLiteError(Exception):
    """An expected user-facing GitLite failure."""


class RepositoryError(GitLiteError):
    pass


class UsageError(GitLiteError):
    pass

from copy import deepcopy


def with_username(user, username):
    """Return a username-only document mutation without changing account state."""
    updated = deepcopy(user)
    updated["username"] = username
    return updated

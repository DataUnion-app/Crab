def parse_allowed_origins(value):
    if not value:
        return []
    origins = []
    for origin in value.split(","):
        origin = origin.strip().rstrip("/")
        if origin and origin != "*" and origin not in origins:
            origins.append(origin)
    return origins


def content_length_bytes(megabytes):
    if megabytes < 1 or megabytes > 100:
        raise ValueError("max_content_length_mb must be between 1 and 100")
    return megabytes * 1024 * 1024

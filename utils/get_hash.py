import hashlib

def get_hash(content):
    return hashlib.sha256(content.encode()).hexdigest()


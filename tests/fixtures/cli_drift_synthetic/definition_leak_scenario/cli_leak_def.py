
# CLI with undocumented internal flag
flags = {
    "--inspect": {"type": "flag", "default": False},
    "--verbose": {"type": "flag", "default": False},
    "--internal": {"type": "flag", "default": False, "description": "INTERNAL USE ONLY"},
}

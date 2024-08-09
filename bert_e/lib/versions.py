

def version_key(version):
    """Key function to sort versions in descending order."""
    parts = version.split('.')
    parts = tuple(int(part) for part in parts)
    # Convert parts to integers and fill missing parts with float('inf')
    return parts + (float('inf'),) * (4 - len(parts))

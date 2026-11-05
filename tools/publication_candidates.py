"""Separate already-reviewed original candidates without changing identity gates.

The caller must statically qualify records and verify any dependency-variant
bindings before calling.  This helper neither grants qualification nor creates
variants.  build_plan remains the final immutable-identity guard.
"""
from collections import defaultdict


def partition_publication_candidates(records, published, identity, is_variant):
    """Return admitted_sha256s and pending collision descriptions.

    published maps canonical identity keys to published rows.  Input order is
    retained for unique admitted SHA values.  Unbound canonical candidates with
    the same identity and differing SHAs are all left pending.
    """
    candidates = []
    seen = {}
    groups = defaultdict(set)
    for record in records:
        sha = record['sha256']
        key = identity(record)
        variant = bool(is_variant(record))
        previous = seen.get(sha)
        if previous is not None:
            if previous != (key, variant):
                raise ValueError('One artifact has inconsistent publication classifications')
            continue
        seen[sha] = (key, variant)
        candidates.append((sha, key, variant))
        if not variant:
            groups[key].add(sha)

    admitted, collisions = [], []
    for sha, key, variant in candidates:
        if variant:
            admitted.append(sha)
            continue
        existing = published.get(key)
        incoming = groups[key]
        if existing is not None:
            existing_sha = existing['sha256']
            collision = sha != existing_sha
            conflicting = (incoming | {existing_sha}) - {sha}
        else:
            collision = len(incoming) > 1
            conflicting = incoming - {sha}
        if collision:
            collisions.append({'sha256': sha,
                               'conflicting_sha256s': sorted(conflicting),
                               'status': 'pending_identity_classification'})
        else:
            admitted.append(sha)
    return {'admitted_sha256s': admitted, 'collisions': collisions}

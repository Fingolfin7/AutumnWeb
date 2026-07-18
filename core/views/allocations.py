def parse_allocation_post(post, subprojects):
    """Return explicit (subproject, bp) pairs, or None when no editor posted."""
    keys = [key for key in post.keys() if key.startswith("alloc_bp_")]
    if not keys:
        return None

    selected = {subproject.pk: subproject for subproject in subprojects}
    expected_keys = {f"alloc_bp_{subproject_id}" for subproject_id in selected}
    if set(keys) != expected_keys:
        raise ValueError("The submitted allocation rows do not match the selected subprojects.")

    allocations = []
    total = 0
    for subproject_id in sorted(selected):
        raw_value = post.get(f"alloc_bp_{subproject_id}")
        try:
            allocation_bp = int(raw_value)
        except (TypeError, ValueError) as exc:
            raise ValueError("Allocation percentages must be whole numbers.") from exc
        if not 1 <= allocation_bp <= 10000 or allocation_bp % 100:
            raise ValueError("Each allocation must be a whole percent from 1% to 100%.")
        total += allocation_bp
        allocations.append((selected[subproject_id], allocation_bp))
    if total > 10000:
        raise ValueError("Allocation percentages must not total more than 100%.")
    return allocations

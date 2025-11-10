def _split_batches(items, max_count, max_bytes):
    """Simple batching helper used by the client: split items into batches
    by max_count and max_bytes. items is an iterable of (name, size).
    """
    batches = []
    cur = []
    cur_bytes = 0
    for name, size in items:
        # If adding this item would exceed count or byte limits, start a new batch
        if cur and (len(cur) >= max_count or (cur_bytes + size) > max_bytes):
            batches.append(cur)
            cur = []
            cur_bytes = 0
        cur.append(name)
        cur_bytes += size
    if cur:
        batches.append(cur)
    return batches


def test_split_batches_by_count_and_bytes():
    items = [('a', 10), ('b', 20), ('c', 30), ('d', 5)]
    batches = _split_batches(items, max_count=2, max_bytes=35)
    # Expect first batch [a,b] (10+20=30 <= 35, count=2), second [c,d] (30+5=35)
    assert batches == [['a', 'b'], ['c', 'd']]

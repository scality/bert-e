from bert_e.exceptions import MasterQueueMissing


def test_master_queue_missing_major_only():
    # Covers version with length 1
    exc = MasterQueueMissing((10,))
    assert 'q/10 is missing' in str(exc)


def test_master_queue_missing_major_minor():
    # Covers version with length 2
    exc = MasterQueueMissing((10, 0))
    assert 'q/10.0 is missing' in str(exc)


def test_master_queue_missing_major_minor_none_micro():
    # Covers version with length >=3 and micro is None
    exc = MasterQueueMissing((10, 0, None))
    assert 'q/10.0 is missing' in str(exc)


def test_master_queue_missing_major_minor_micro():
    # Covers version with length >=3 and micro is not None
    exc = MasterQueueMissing((10, 0, 5))
    assert 'q/10.0.5 is missing' in str(exc)


def test_master_queue_missing_fallback():
    # Covers fallback case
    exc = MasterQueueMissing([])
    assert 'q/[] is missing' in str(exc)

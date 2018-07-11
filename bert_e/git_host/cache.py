from bert_e.lib.lru_cache import LRUCache
from collections import defaultdict

BUILD_STATUS_CACHE = defaultdict(LRUCache)  # type: Dict[str, LRUCache]

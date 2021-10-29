from bert_e.lib.lru_cache import LRUCache
from collections import defaultdict, OrderedDict

BUILD_STATUS_CACHE = defaultdict(LRUCache)  # type: OrderedDict[str, LRUCache]

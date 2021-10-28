
import pytest
import logging
import os.path
from bert_e.settings import BertEContextFilter, setup_settings


@pytest.fixture
def settings():
    """Simple settings fixture."""
    return setup_settings(os.path.abspath('settings.sample.yml'))


def test_log_filter(settings):
    """Test a simple instanciation of BertEContextFilter."""
    logging.basicConfig(format='%(instance)s - %(level)s - %(message)s')
    logger = logging.getLogger(__name__)
    log_filter = BertEContextFilter(settings)
    logger.addFilter(log_filter)
    logger.info('hello')
    assert len(logger.filters) == 1

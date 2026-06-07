import logging
from pathlib import Path

logger = logging.getLogger(__name__)

# Project root is parent of src/ directory
_project_root = Path(__file__).resolve().parent.parent
_config_path = _project_root / 'config.yaml'

if _config_path.is_file():
    logger.info('Config found at %s', _config_path)
else:
    logger.debug('Config file not found at %s (will use defaults)', _config_path)

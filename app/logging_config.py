import logging
import sys


def setup_logging():
    logger = logging.getLogger("media_pipeline")
    logger.setLevel(logging.INFO)
    if not logger.handlers:
        handler = logging.StreamHandler(sys.stdout)
        formatter = logging.Formatter(
            '{"time":"%(asctime)s","level":"%(levelname)s","logger":"%(name)s","msg":"%(message)s"}'
        )
        handler.setFormatter(formatter)
        logger.addHandler(handler)
    return logger

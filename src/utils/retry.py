import time
import random
import functools
import logging


def retry_with_backoff(
    max_attempts: int = 3,
    base_delay: float = 2.0,
    max_delay: float = 60.0,
    exceptions: tuple = (Exception,),
    logger_name: str = "zhihu_analyst"
):
    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            _logger = logging.getLogger(logger_name)
            last_exc = None
            for attempt in range(max_attempts):
                try:
                    return func(*args, **kwargs)
                except exceptions as e:
                    last_exc = e
                    if attempt == max_attempts - 1:
                        _logger.error(
                            f"{func.__name__} 已达最大重试次数({max_attempts})，最终失败: {e}"
                        )
                        raise
                    delay = min(base_delay * (2 ** attempt) + random.uniform(0, 1), max_delay)
                    _logger.warning(
                        f"{func.__name__} 第{attempt + 1}次失败: {type(e).__name__}: {e}，"
                        f"{delay:.1f}s 后重试..."
                    )
                    time.sleep(delay)
            raise last_exc
        return wrapper
    return decorator

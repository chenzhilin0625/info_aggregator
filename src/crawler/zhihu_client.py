"""
知乎 API 客户端（Cookie 认证）
"""
import re
import logging
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from src.utils.retry import retry_with_backoff

logger = logging.getLogger("zhihu_analyst")

BASE_URL = "https://www.zhihu.com"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Referer": "https://www.zhihu.com/",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "zh-CN,zh;q=0.9",
    "x-requested-with": "fetch",
    "x-app-za": "OS=Web",
    "x-api-version": "3.0.0",
}


class CookieExpiredError(Exception):
    """Cookie 已过期或无效"""


class ZhihuClient:
    def __init__(self, cookie_z_c0: str):
        cookie_value = cookie_z_c0.strip()
        if cookie_value.startswith("z_c0="):
            cookie_value = cookie_value[5:]

        self.session = requests.Session()
        self.session.headers.update(HEADERS)

        adapter = HTTPAdapter(
            max_retries=Retry(total=3, backoff_factor=1,
                              status_forcelist=[500, 502, 503, 504])
        )
        self.session.mount("https://", adapter)
        self.session.cookies.set("z_c0", cookie_value, domain=".zhihu.com")
        self._inject_xsrf()

    def _inject_xsrf(self):
        try:
            resp = self.session.get(f"{BASE_URL}/", timeout=15)
            resp.raise_for_status()
            xsrf = self.session.cookies.get("_xsrf")
            if xsrf:
                self.session.headers["x-xsrftoken"] = xsrf
                logger.debug("xsrf token 注入成功")
            else:
                logger.warning("未获取到 _xsrf token")
        except Exception as e:
            logger.warning(f"注入 xsrf 时出错: {e}")

    def validate_cookie(self) -> bool:
        try:
            resp = self.session.get(f"{BASE_URL}/api/v4/me", timeout=10)
            if resp.status_code == 200:
                data = resp.json()
                if "id" in data or "uid" in data:
                    name = data.get("name", "未知用户")
                    self._my_url_token = data.get("url_token", "")
                    logger.info(f"Cookie 验证成功，当前用户：{name}")
                    return True
            logger.warning(f"Cookie 验证失败，HTTP {resp.status_code}")
            return False
        except Exception as e:
            logger.warning(f"Cookie 验证请求失败: {e}")
            return False

    def fetch_followees(self) -> set[str]:
        """获取当前用户关注的所有账号的 url_token 集合"""
        if not hasattr(self, '_my_url_token') or not self._my_url_token:
            self.validate_cookie()

        followees = set()
        page = 0
        while True:
            try:
                resp = self.session.get(
                    f"{BASE_URL}/api/v4/members/{self._my_url_token}/followees",
                    params={"limit": 20, "offset": page * 20},
                    timeout=15,
                )
                resp.raise_for_status()
                data = resp.json()
                for f in data.get("data", []):
                    followees.add(f.get("url_token", ""))
                if data.get("paging", {}).get("is_end", True):
                    break
                page += 1
            except Exception as e:
                logger.error(f"获取关注列表失败（第{page}页）: {e}")
                break

        logger.info(f"已获取关注列表：{len(followees)} 人")
        return followees

    def fetch_member_answers(self, url_token: str, limit: int = 5) -> list[dict]:
        """获取某个用户的最新回答列表（原始 JSON，不含 content）"""
        resp = self.session.get(
            f"{BASE_URL}/api/v4/members/{url_token}/answers",
            params={"limit": limit, "sort_by": "created"},
            timeout=15,
        )
        resp.raise_for_status()
        return resp.json().get("data", [])

    def fetch_answer_content(self, answer_id: int) -> str:
        """获取单个回答的正文 HTML 内容"""
        resp = self.session.get(
            f"{BASE_URL}/api/v4/answers/{answer_id}",
            params={"include": "content"},
            timeout=15,
        )
        resp.raise_for_status()
        return resp.json().get("content", "")

    def fetch_member_articles(self, url_token: str, limit: int = 5) -> list[dict]:
        """获取某个用户的最新文章列表（原始 JSON）"""
        resp = self.session.get(
            f"{BASE_URL}/api/v4/members/{url_token}/articles",
            params={"limit": limit, "sort_by": "created"},
            timeout=15,
        )
        resp.raise_for_status()
        return resp.json().get("data", [])

    def fetch_member_pins(self, url_token: str, limit: int = 5) -> list[dict]:
        """获取某个用户的最新想法列表（原始 JSON）"""
        resp = self.session.get(
            f"{BASE_URL}/api/v4/members/{url_token}/pins",
            params={"limit": limit},
            timeout=15,
        )
        resp.raise_for_status()
        return resp.json().get("data", [])

    @retry_with_backoff(max_attempts=3, base_delay=2.0,
                        exceptions=(requests.HTTPError, requests.Timeout,
                                    requests.ConnectionError))
    def get_feed_page(self, next_url: str = None, limit: int = 20) -> dict:
        """
        获取关注流单页数据。首次调用传 next_url=None。
        后续翻页使用上一次响应的 paging.next URL。

        注意：知乎新版已不区分关注/推荐独立 API，
        统一使用 /api/v3/feed/topstory，主要为关注账户内容。
        """
        if next_url:
            full_url = next_url if next_url.startswith("http") else f"{BASE_URL}{next_url}"
            # next_url 已包含所有参数，直接请求
            resp = self.session.get(full_url, timeout=20)
        else:
            url = f"{BASE_URL}/api/v3/feed/topstory"
            params = {"limit": limit}
            resp = self.session.get(url, params=params, timeout=20)

        if resp.status_code in (401, 403):
            raise CookieExpiredError(
                f"HTTP {resp.status_code}，Cookie 可能已过期或被封禁"
            )

        resp.raise_for_status()
        data = resp.json()
        if "error" in data:
            logger.warning(f"知乎 API 返回错误: {data['error']}")
        return data

"""
DeepSeek API 封装：费用追踪、限流重试
通过 OpenAI 兼容 SDK 调用 DeepSeek
"""
import logging
import time

from openai import OpenAI, RateLimitError

logger = logging.getLogger("zhihu_analyst")

# DeepSeek 官方定价（USD/1M tokens）
# deepseek-chat:  $0.27 input, $1.10 output
# deepseek-reasoner: $0.55 input, $2.19 output
MODEL_PRICING = {
    "deepseek-chat":     {"input": 0.27, "output": 1.10},
    "deepseek-reasoner": {"input": 0.55, "output": 2.19},
}


class DeepSeekClient:
    def __init__(self, api_key: str, cfg: dict):
        base_url = cfg.get("base_url", "https://api.deepseek.com")
        self.client = OpenAI(api_key=api_key, base_url=base_url)
        self.classify_model = cfg.get("classify_model", "deepseek-chat")
        self.extract_model = cfg.get("extract_model", "deepseek-chat")
        self.synthesize_model = cfg.get("synthesize_model", "deepseek-chat")
        self.cost_limit = cfg.get("daily_cost_limit_usd", 0.50)

        self.cost_tracker = {
            "input_tokens": 0,
            "output_tokens": 0,
            "cache_read_tokens": 0,
            "cache_write_tokens": 0,
            "cost_usd": 0.0,
            "api_calls": 0,
        }

    def complete(
        self,
        system: str,
        user: str,
        model: str,
        max_tokens: int = 1024,
        use_cache: bool = False,
    ) -> str:
        """
        调用 DeepSeek API（OpenAI 兼容接口），返回文本响应。

        Args:
            system: 系统提示词
            user: 用户消息
            model: 模型 ID（deepseek-chat 或 deepseek-reasoner）
            max_tokens: 最大输出 token
            use_cache: DeepSeek 默认启用磁盘缓存，此参数保留但不生效
        """
        if self.cost_tracker["cost_usd"] >= self.cost_limit:
            raise RuntimeError(
                f"已达每日费用上限 ${self.cost_limit:.2f}，"
                f"当前已消耗 ${self.cost_tracker['cost_usd']:.4f}"
            )

        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ]

        for attempt in range(5):
            try:
                resp = self.client.chat.completions.create(
                    model=model,
                    messages=messages,
                    max_tokens=max_tokens,
                    temperature=0.1,
                )
                break
            except RateLimitError as e:
                if attempt == 4:
                    raise
                wait = 10 * (2 ** attempt)
                logger.warning(
                    f"DeepSeek API 限流，{wait}s 后重试（第{attempt+1}次）: {e}"
                )
                time.sleep(wait)
            except Exception as e:
                status = getattr(e, "status_code", 0)
                if status >= 500 and attempt < 4:
                    wait = 5 * (2 ** attempt)
                    logger.warning(
                        f"DeepSeek API 服务端错误 {status}，{wait}s 后重试"
                    )
                    time.sleep(wait)
                else:
                    raise

        # 费用追踪
        usage = resp.usage
        input_tk = usage.prompt_tokens
        output_tk = usage.completion_tokens

        # 尝试读取缓存命中信息（DeepSeek 自动磁盘缓存，API 返回中可能有）
        cache_read_tk = getattr(usage, "prompt_cache_hit_tokens", 0) or 0

        pricing = MODEL_PRICING.get(model, {"input": 0.27, "output": 1.10})
        cost = (
            (input_tk / 1_000_000) * pricing["input"]
            + (output_tk / 1_000_000) * pricing["output"]
        )

        self.cost_tracker["input_tokens"] += input_tk
        self.cost_tracker["output_tokens"] += output_tk
        self.cost_tracker["cache_read_tokens"] += cache_read_tk
        self.cost_tracker["cost_usd"] += cost
        self.cost_tracker["api_calls"] += 1

        logger.debug(
            f"[{model}] in={input_tk} out={output_tk} "
            f"cache_hit={cache_read_tk} "
            f"cost=${cost:.5f} 累计=${self.cost_tracker['cost_usd']:.4f}"
        )

        return resp.choices[0].message.content

    def summary_cost(self) -> str:
        t = self.cost_tracker
        return (
            f"API调用{t['api_calls']}次，"
            f"输入{t['input_tokens']}token，"
            f"输出{t['output_tokens']}token，"
            f"总费用约 ${t['cost_usd']:.4f}"
        )

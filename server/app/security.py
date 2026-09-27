"""接口鉴权。

分两个令牌，职责分开：

* 上报令牌(IAP_AGENT_TOKEN)：装在终端上的 Agent 使用，只够调用上报接口。
  Agent 分发给别人也不会导致看板数据泄露，因为它读不到任何数据。
* 读取令牌(IAP_READ_TOKEN)：看板使用，可以查看设备、告警、统计，也可以
  补录资产信息和标记告警。装在别人电脑上的 Agent 拿不到这个值。

两个令牌都通过环境变量注入，比较时使用固定时间比较，避免时序侧信道。
"""

from __future__ import annotations

import hmac

from fastapi import Header, HTTPException

from .config import settings


def require_agent_token(x_agent_token: str | None = Header(default=None)) -> None:
    expected = settings.agent_token or ""
    provided = x_agent_token or ""
    if not expected or not hmac.compare_digest(provided, expected):
        raise HTTPException(status_code=401, detail="上报令牌无效")


def require_read_token(x_read_token: str | None = Header(default=None)) -> None:
    expected = settings.read_token or ""
    provided = x_read_token or ""
    if not expected or not hmac.compare_digest(provided, expected):
        raise HTTPException(status_code=401, detail="读取令牌无效")

"""统一错误码（SRS 8.3）。

规则：业务码与 HTTP 状态码分离，响应体固定为
``{"code": 40001, "message": "...", "hint": "...", "trace_id": "..."}``。
前端按 ``code`` 分支，不按 ``message`` 文案匹配。
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ErrorSpec:
    http_status: int
    message: str
    hint: str


# SRS 8.3 全表，未定义的一律走 50001
ERROR_SPECS: dict[int, ErrorSpec] = {
    40001: ErrorSpec(400, "文件编码无法识别", "请另存为 UTF-8 后重新上传"),
    40002: ErrorSpec(400, "行数或体积超出上限", "单文件 ≤ 50 MB、≤ 20 万行（C-02）"),
    40003: ErrorSpec(400, "非 CSV 文件或缺少表头", "请检查首行是否为列名"),
    40004: ErrorSpec(400, "必填字段未映射", "请在映射页为缺失字段指定来源列"),
    41301: ErrorSpec(413, "文件过大", "请拆分文件后分批上传"),
    42201: ErrorSpec(422, "参数校验失败", "请检查标红字段"),
    40901: ErrorSpec(409, "数据集已存在（文件哈希命中）", "可选择覆盖或复用已有数据集"),
    40902: ErrorSpec(409, "用户名已存在", "请换一个用户名，或直接登录"),
    40101: ErrorSpec(401, "令牌无效或已过期", "请重新登录"),
    40102: ErrorSpec(401, "旧密码错误", "请确认当前密码"),
    40301: ErrorSpec(403, "无权访问该数据集", ""),
    # 40401 与 40301 共用语义，避免通过错误码枚举他人数据集（FR-28 异常行）
    40401: ErrorSpec(404, "数据集不存在或已被删除", "请返回数据集列表"),
    40402: ErrorSpec(404, "样本序号不存在", "该样本不在当前筛选结果中，请刷新图表"),
    42901: ErrorSpec(429, "触发限流", "请稍后重试"),
    42902: ErrorSpec(429, "账号因连续登录失败被锁定", "请 15 分钟后再试"),
    50001: ErrorSpec(500, "计算异常", "请记录 trace_id 后反馈"),
}


class AppError(Exception):
    """业务异常。在 API 层被统一转换为 8.3 的错误响应。"""

    def __init__(self, code: int, detail: str | None = None, *, extra: dict | None = None):
        spec = ERROR_SPECS.get(code, ERROR_SPECS[50001])
        self.code = code
        self.http_status = spec.http_status
        self.message = spec.message
        self.hint = spec.hint
        self.detail = detail
        self.extra = extra or {}
        super().__init__(f"[{code}] {spec.message}" + (f": {detail}" if detail else ""))

    def to_payload(self, trace_id: str | None = None) -> dict:
        payload = {
            "code": self.code,
            "message": self.message,
            "hint": self.hint,
            "detail": self.detail,
        }
        if trace_id:
            payload["trace_id"] = trace_id
        payload.update(self.extra)
        return payload


class MissingFieldsError(AppError):
    """FR-02：必填字段未识别 → 阻塞上传（40004）。"""

    def __init__(self, missing: list[str]):
        super().__init__(
            40004,
            detail="缺少：" + "、".join(missing),
            extra={"missing_fields": missing},
        )


class UnitAmbiguousError(AppError):
    """3.4：中位数落在两个量级之间 → 弹"请确认单位"，不静默换算。"""

    def __init__(self, field: str, median: float, candidates: list[str]):
        super().__init__(
            42201,
            detail=f"{field} 的列中位数 {median:g} 无法判定单位（可能为 {' / '.join(candidates)}）",
            extra={"field": field, "median": median, "candidates": candidates},
        )

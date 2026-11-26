"""运行配置（SRS 2.3 运行环境、2.4 设计约束 C-02）。

所有路径与上限集中在这里，业务代码不得自行拼接路径或硬编码 50 MB / 20 万行这类数字。
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

# backend/app/core/config.py -> backend/app/core -> backend/app -> backend -> cbc-insight
BACKEND_DIR = Path(__file__).resolve().parents[2]
PROJECT_ROOT = BACKEND_DIR.parent  # 仅用于文档/脚本定位仓库根，后端运行时不依赖它


class Settings(BaseSettings):
    # env_file 指到 backend/.env（而不是相对 CWD 的 ".env"）：从仓库根、从 backend/、
    # 从 IDE 三种方式启动时都要读到同一份配置，否则"在我这儿能连上"会变成玄学。
    # 进程环境变量的优先级高于文件，已存在的同名变量不会被文件覆盖。
    model_config = SettingsConfigDict(
        env_prefix="CBC_", env_file=str(BACKEND_DIR / ".env"), extra="ignore"
    )

    app_name: str = "CBC Insight"
    api_prefix: str = "/api/v1"
    disclaimer: str = (
        "本系统仅用于数据分析方法的教学与演示，所有输出均基于公开脱敏数据集的统计计算，"
        "不构成任何医学诊断、治疗建议或健康评估结论。"
    )

    # --- 路径（7.5 计算与存储分工表） ---
    # 运行时数据（上传件、中间结果、渲染图、默认 SQLite 库）一律放 backend/data/，
    # 与后端代码同属一个可移植单元：整个 backend/ 目录拷到别处仍能独立跑。
    data_dir: Path = BACKEND_DIR / "data"
    resources_dir: Path = BACKEND_DIR / "resources"

    @property
    def backend_dir(self) -> Path:
        """``backend/`` 目录（alembic.ini 与 alembic/ 所在处）。"""
        return BACKEND_DIR

    # --- 存储 ---
    # 默认 SQLite 仅用于零依赖起步；接入 Postgres 时用环境变量覆盖，例如
    #   CBC_DATABASE_URL=postgresql+psycopg://cbc:cbc@127.0.0.1:5432/cbc
    # 此时数据在 PG 实例（WSL/Docker）里，backend/data/ 下不会出现任何数据库文件。
    database_url: str = f"sqlite:///{(BACKEND_DIR / 'data' / 'app.db').as_posix()}"
    redis_url: str | None = None  # 未配置时退化为进程内实现（单机开发）

    # --- 规模上限（2.4 C-02、3.8） ---
    max_upload_bytes: int = 50 * 1024 * 1024
    max_rows: int = 200_000
    max_columns: int = 60
    max_datasets_per_user: int = 20
    preview_page_size: int = 100
    points_limit: int = 2000  # NFR-P-09：单图点位载荷上限

    # --- 鉴权（NFR-S-02、FR-34） ---
    # 开发默认值故意写得很长：HS256 的密钥短于 32 字节会被 PyJWT 警告，
    # 而"警告没人看"正是生产环境里用弱密钥的方式。部署时必须用环境变量覆盖。
    jwt_secret: str = "dev-only-secret-change-me-0123456789abcdef"
    jwt_algorithm: str = "HS256"
    access_token_minutes: int = 30
    refresh_token_days: int = 7
    bcrypt_cost: int = 12
    login_max_failures: int = 5
    login_lock_minutes: int = 15

    # --- 清洗（NFR-P-02：超过该秒数转异步，MVP 阶段同步执行并记录耗时） ---
    sync_clean_budget_seconds: float = 30.0

    host: str = "127.0.0.1"  # NFR-S-08：默认仅监听本机
    port: int = 8000

    allowed_origins: list[str] = Field(default_factory=lambda: ["http://localhost:5173"])

    @property
    def raw_dir(self) -> Path:
        return self.data_dir / "raw"

    @property
    def processed_dir(self) -> Path:
        return self.data_dir / "processed"

    @property
    def rendered_dir(self) -> Path:
        return self.data_dir / "rendered"

    @property
    def reports_dir(self) -> Path:
        return self.data_dir / "reports"

    @property
    def reference_ranges_path(self) -> Path:
        return self.resources_dir / "reference_ranges.yaml"

    @property
    def field_dict_path(self) -> Path:
        return self.resources_dir / "field_dict.yaml"

    @property
    def field_mapping_path(self) -> Path:
        return self.resources_dir / "field_mapping.yaml"

    @property
    def cleaning_strategy_path(self) -> Path:
        return self.resources_dir / "cleaning_strategy.yaml"

    @property
    def caption_templates_path(self) -> Path:
        return self.resources_dir / "caption_templates.yaml"

    def ensure_dirs(self) -> None:
        for path in (
            self.data_dir,
            self.raw_dir,
            self.processed_dir,
            self.rendered_dir,
            self.reports_dir,
        ):
            path.mkdir(parents=True, exist_ok=True)


@lru_cache
def get_settings() -> Settings:
    return Settings()

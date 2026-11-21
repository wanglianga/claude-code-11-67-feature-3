import os


class Settings:
    """应用配置。所有项均可通过环境变量覆盖，默认值仅用于本地开发。"""

    DATABASE_URL: str = os.getenv(
        "DATABASE_URL",
        "postgresql+psycopg2://ccdev:ccdev@127.0.0.1:5432/ccdev",
    )
    # 令牌签名密钥：生产环境必须通过环境变量注入
    SECRET_KEY: str = os.getenv("SECRET_KEY", "dev-only-secret-change-me")
    TOKEN_TTL_HOURS: int = int(os.getenv("TOKEN_TTL_HOURS", "12"))
    # 是否在启动时自动建表（本地开发与演示开启）
    AUTO_CREATE_TABLES: bool = os.getenv("AUTO_CREATE_TABLES", "1") == "1"


settings = Settings()

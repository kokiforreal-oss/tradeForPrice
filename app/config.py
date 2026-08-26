from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
UPLOAD_DIR = DATA_DIR / "uploads"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=str(BASE_DIR / ".env"), extra="ignore")

    secret_key: str = "dev-secret-change-on-ecs"
    # 默认免费社区版 MySQL 8（PyMySQL）。也可用 mysql://，database.py 会改成 mysql+pymysql://
    database_url: str = "mysql+pymysql://trade:trade123@127.0.0.1:3306/trade?charset=utf8mb4"
    access_token_expire_hours: int = 24
    # 生产默认关闭 Swagger；本机调试可在 .env 设 ENABLE_API_DOCS=true
    enable_api_docs: bool = False


settings = Settings()
DATA_DIR.mkdir(parents=True, exist_ok=True)
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
(UPLOAD_DIR / "contracts").mkdir(exist_ok=True)

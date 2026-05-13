from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # LLM
    openai_api_key: str = "sk-your-key-here"
    openai_base_url: str = "https://api.openai.com/v1"
    llm_model: str = "gpt-4o"
    llm_embedding_model: str = "text-embedding-3-small"

    # PostgreSQL
    postgres_host: str = "localhost"
    postgres_port: int = 5433
    postgres_db: str = "chatbi_demo"
    postgres_user: str = "postgres"
    postgres_password: str = "123456"
    postgres_schema: str = "analytics"

    # dbt
    dbt_project_dir: str = "./dbt_project"
    dbt_profiles_dir: str = "./dbt_project"

    # App
    app_host: str = "0.0.0.0"
    app_port: int = 8000
    max_query_timeout: int = 30
    max_result_rows: int = 1000

    # ChromaDB
    chroma_persist_dir: str = "./chroma_db"

    @property
    def database_url(self) -> str:
        return (
            f"postgresql+asyncpg://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )

    @property
    def database_sync_url(self) -> str:
        return (
            f"postgresql+psycopg2://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


settings = Settings()

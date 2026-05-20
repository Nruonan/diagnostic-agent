from app.config import Settings
from app.storage.base import DiagnosisStore
from app.storage.json_store import JsonDiagnosisStore


def build_diagnosis_store(settings: Settings) -> DiagnosisStore:
    if settings.storage_mode == "postgres":
        from app.storage.postgres_store import PostgresDiagnosisStore

        return PostgresDiagnosisStore(settings.database_url)
    return JsonDiagnosisStore(settings.runtime_dir)


__all__ = ["DiagnosisStore", "JsonDiagnosisStore", "build_diagnosis_store"]

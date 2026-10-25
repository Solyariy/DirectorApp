APPS_SCHEMA = "apps"


def apps_table(name: str) -> str:
    # Quoted so Django keeps the schema prefix (Postgres only).
    return f'"{APPS_SCHEMA}"."{name}"'

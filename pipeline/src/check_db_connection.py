import os
import sys

import psycopg


def get_required_env(name: str) -> str:
    value = os.getenv(name)

    if not value:
        print(f"Missing required environment variable: {name}")
        sys.exit(1)

    return value


def main() -> None:
    db_user = get_required_env("POSTGRES_USER")
    db_password = get_required_env("POSTGRES_PASSWORD")
    db_name = get_required_env("POSTGRES_DB")
    db_host = get_required_env("POSTGRES_HOST")
    db_port = get_required_env("POSTGRES_PORT")

    connection_string = (
        f"postgresql://{db_user}:{db_password}"
        f"@{db_host}:{db_port}/{db_name}"
    )

    print("Trying to connect to PostgreSQL...")

    try:
        with psycopg.connect(connection_string) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT current_database(), current_user;")
                database_name, current_user = cur.fetchone()

                print("Connection successful.")
                print(f"Database: {database_name}")
                print(f"User: {current_user}")

                cur.execute("""
                    SELECT table_name
                    FROM information_schema.tables
                    WHERE table_schema = 'public'
                    ORDER BY table_name;
                """)

                tables = cur.fetchall()

                print("Available tables:")

                if not tables:
                    print("- No tables found.")
                else:
                    for table in tables:
                        print(f"- {table[0]}")

    except Exception as error:
        print("Connection failed.")
        print(error)
        sys.exit(1)


if __name__ == "__main__":
    main()
import os
import sqlite3
from pathlib import Path


class UserStore:
    def __init__(self, db_path: str | None = None) -> None:
        db_path = db_path or os.getenv("BOT_DB_PATH", "bot.db")
        self.db_path = Path(db_path)
        self._memory_connection: sqlite3.Connection | None = None
        if db_path == ":memory:":
            self._memory_connection = sqlite3.connect(db_path)
        else:
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        if self._memory_connection is not None:
            return self._memory_connection
        return sqlite3.connect(self.db_path)

    def _init_db(self) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS users (
                    telegram_user_id INTEGER PRIMARY KEY,
                    redmine_api_key TEXT NOT NULL
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS favorite_projects (
                    telegram_user_id INTEGER NOT NULL,
                    project_id INTEGER NOT NULL,
                    project_name TEXT NOT NULL,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (telegram_user_id, project_id)
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS recent_issues (
                    telegram_user_id INTEGER NOT NULL,
                    issue_id INTEGER NOT NULL,
                    issue_subject TEXT NOT NULL,
                    project_id INTEGER,
                    project_name TEXT,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (telegram_user_id, issue_id)
                )
                """
            )

    def save_api_key(self, telegram_user_id: int, api_key: str) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO users (telegram_user_id, redmine_api_key)
                VALUES (?, ?)
                ON CONFLICT(telegram_user_id)
                DO UPDATE SET redmine_api_key = excluded.redmine_api_key
                """,
                (telegram_user_id, api_key),
            )

    def get_api_key(self, telegram_user_id: int) -> str | None:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT redmine_api_key
                FROM users
                WHERE telegram_user_id = ?
                """,
                (telegram_user_id,),
            ).fetchone()

        return row[0] if row else None

    def delete_api_key(self, telegram_user_id: int) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                DELETE FROM users
                WHERE telegram_user_id = ?
                """,
                (telegram_user_id,),
            )

    def save_favorite_project(
        self,
        telegram_user_id: int,
        project_id: int,
        project_name: str,
    ) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO favorite_projects (
                    telegram_user_id,
                    project_id,
                    project_name,
                    updated_at
                )
                VALUES (?, ?, ?, strftime('%Y-%m-%d %H:%M:%f', 'now'))
                ON CONFLICT(telegram_user_id, project_id)
                DO UPDATE SET
                    project_name = excluded.project_name,
                    updated_at = strftime('%Y-%m-%d %H:%M:%f', 'now')
                """,
                (telegram_user_id, project_id, project_name),
            )

    def delete_favorite_project(self, telegram_user_id: int, project_id: int) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                DELETE FROM favorite_projects
                WHERE telegram_user_id = ? AND project_id = ?
                """,
                (telegram_user_id, project_id),
            )

    def is_favorite_project(self, telegram_user_id: int, project_id: int) -> bool:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT 1
                FROM favorite_projects
                WHERE telegram_user_id = ? AND project_id = ?
                """,
                (telegram_user_id, project_id),
            ).fetchone()

        return row is not None

    def get_favorite_project(
        self,
        telegram_user_id: int,
        project_id: int,
    ) -> dict[str, object] | None:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT project_id, project_name
                FROM favorite_projects
                WHERE telegram_user_id = ? AND project_id = ?
                """,
                (telegram_user_id, project_id),
            ).fetchone()

        if not row:
            return None

        return {"id": row[0], "name": row[1]}

    def get_favorite_projects(
        self,
        telegram_user_id: int,
        limit: int,
    ) -> list[dict[str, object]]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT project_id, project_name
                FROM favorite_projects
                WHERE telegram_user_id = ?
                ORDER BY updated_at DESC
                LIMIT ?
                """,
                (telegram_user_id, limit),
            ).fetchall()

        return [{"id": row[0], "name": row[1]} for row in rows]

    def save_recent_issue(
        self,
        telegram_user_id: int,
        issue_id: int,
        issue_subject: str,
        project_id: int | None,
        project_name: str | None,
        limit: int,
    ) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO recent_issues (
                    telegram_user_id,
                    issue_id,
                    issue_subject,
                    project_id,
                    project_name,
                    updated_at
                )
                VALUES (?, ?, ?, ?, ?, strftime('%Y-%m-%d %H:%M:%f', 'now'))
                ON CONFLICT(telegram_user_id, issue_id)
                DO UPDATE SET
                    issue_subject = excluded.issue_subject,
                    project_id = excluded.project_id,
                    project_name = excluded.project_name,
                    updated_at = strftime('%Y-%m-%d %H:%M:%f', 'now')
                """,
                (telegram_user_id, issue_id, issue_subject, project_id, project_name),
            )
            connection.execute(
                """
                DELETE FROM recent_issues
                WHERE telegram_user_id = ?
                  AND issue_id NOT IN (
                    SELECT issue_id
                    FROM recent_issues
                    WHERE telegram_user_id = ?
                    ORDER BY updated_at DESC
                    LIMIT ?
                  )
                """,
                (telegram_user_id, telegram_user_id, limit),
            )

    def get_recent_issues(
        self,
        telegram_user_id: int,
        limit: int,
    ) -> list[dict[str, object]]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT issue_id, issue_subject, project_id, project_name
                FROM recent_issues
                WHERE telegram_user_id = ?
                ORDER BY updated_at DESC
                LIMIT ?
                """,
                (telegram_user_id, limit),
            ).fetchall()

        return [
            {
                "id": row[0],
                "subject": row[1],
                "project_id": row[2],
                "project_name": row[3],
            }
            for row in rows
        ]

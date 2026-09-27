"""Export a destruction journal and an UNSIGNED act draft; never claim a signature."""

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path

from slovech.core.config import get_settings
from slovech.core.storage import Repository


def export_record(row: dict, directory: Path):
    directory.mkdir(mode=0o700, parents=False, exist_ok=False)
    date = datetime.fromtimestamp(row["deleted_at"], UTC).isoformat()
    act = (
        "# Проект акта об уничтожении персональных данных\n\n"
        "**НЕ ПОДПИСАН. Требует проверки и подписи оператора.**\n\n"
        f"Номер: {row['id']}. Дата: {date}.\n\n"
        "Оператор и ответственное лицо: ____________________.\n\n"
        "Адрес для акта: ____________________.\n\n"
        f"Субъект: владелец Telegram ID {row['user_id']}.\n\n"
        f"Категории: {row['categories']}.\n\n"
        f"Область подтверждённой очистки: {row['scope']}.\n\n"
        f"Причина: {row['reason']}.\n\n"
        "Способ: удаление файлов, удаление строк SQLite с secure_delete, VACUUM и очисткой WAL; "
        "перезапись управляемых резервных копий без удалённых строк. Физический носитель не уничтожался.\n\n"
        "Перед подписанием проверить полноту: реквизиты обработчиков по поручению, дополнительные копии "
        "и внешние системы. Их уничтожение этот журнал НЕ подтверждает. Если они участвуют в акте, "
        "добавить полученные подтверждения и реквизиты.\n\n"
        "Подпись ответственного лица: ____________________\n"
    )
    for name, content in (
        ("journal.json", json.dumps(row, ensure_ascii=False, indent=2)),
        ("act-draft.md", act),
    ):
        path = directory / name
        with path.open("x", encoding="utf-8") as stream:
            path.chmod(0o600)
            stream.write(content + "\n")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--record", help="Record ID from --list")
    parser.add_argument("--output", type=Path, help="New private export directory")
    parser.add_argument(
        "--list", action="store_true", help="Show IDs/dates without Telegram identifiers"
    )
    args = parser.parse_args()
    repo = Repository(get_settings())
    with repo.connection() as db:
        if args.list:
            print(
                json.dumps(
                    [
                        dict(r)
                        for r in db.execute(
                            "SELECT id,deleted_at FROM deletion_audit ORDER BY deleted_at DESC"
                        )
                    ]
                )
            )
            return
        if not args.record or not args.output:
            parser.error("Specify --list or both --record and --output")
        row = db.execute("SELECT * FROM deletion_audit WHERE id=?", (args.record,)).fetchone()
        if not row:
            parser.error("Record not found")
        export_record(dict(row), args.output)
    print(
        "Exported journal and UNSIGNED act draft. Verify scope and sign separately; protect and retain the export for 3 years."
    )


if __name__ == "__main__":
    main()

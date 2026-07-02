"""
Менеджер шаблонов сообщений.

Шаблоны хранятся в config/templates.json.
Каждый шаблон имеет кодовое слово и текст с переменными {var}.

Пример команды: "Лимона отправить с компьютера документы @username ПЕРЕДАЧА_ДОКУМЕНТОВ"
→ находит шаблон "ПЕРЕДАЧА_ДОКУМЕНТОВ", подставляет переменные и отправляет @username
"""

import json
import logging
import re
from pathlib import Path
from typing import Optional

log = logging.getLogger("TemplateManager")


class Template:
    def __init__(self, data: dict):
        self.keyword = data["keyword"]          # кодовое слово
        self.name = data.get("name", self.keyword)
        self.text = data["text"]                # текст шаблона с {переменными}
        self.description = data.get("description", "")
        self.variables = self._extract_variables()

    def _extract_variables(self) -> list[str]:
        """Находит все {переменные} в тексте шаблона."""
        return re.findall(r"\{(\w+)\}", self.text)

    def render(self, variables: dict) -> str:
        """Подставляет переменные в шаблон."""
        result = self.text
        for key, value in variables.items():
            result = result.replace(f"{{{key}}}", value)
        return result

    def __repr__(self):
        return f"Template(keyword={self.keyword!r}, vars={self.variables})"


class TemplateManager:
    def __init__(self, templates_file: str):
        self.templates_file = Path(templates_file)
        self.templates: dict[str, Template] = {}
        self._load()

    def _load(self):
        """Загружает шаблоны из JSON файла."""
        if not self.templates_file.exists():
            log.warning(f"Файл шаблонов не найден: {self.templates_file}. Создаю пример.")
            self._create_example()

        try:
            data = json.loads(self.templates_file.read_text(encoding="utf-8"))
            templates_data = data if isinstance(data, list) else data.get("templates", [])

            self.templates = {}
            for t_data in templates_data:
                t = Template(t_data)
                self.templates[t.keyword.upper()] = t
                log.info(f"  📋 Шаблон загружен: {t.keyword} → '{t.name}'")

        except Exception as e:
            log.error(f"Ошибка загрузки шаблонов: {e}")

    def _create_example(self):
        """Создаёт пример файла шаблонов."""
        example = {
            "templates": [
                {
                    "keyword": "ПЕРЕДАЧА_ДОКУМЕНТОВ",
                    "name": "Передача документов",
                    "description": "Шаблон для отправки уведомления о передаче документов",
                    "text": (
                        "Привет! 👋\n\n"
                        "Направляю тебе документы по {тема}.\n\n"
                        "📎 Прикладываю все необходимые материалы.\n"
                        "Дай знать когда получишь.\n\n"
                        "С уважением,\n{отправитель}"
                    )
                },
                {
                    "keyword": "ВСТРЕЧА",
                    "name": "Приглашение на встречу",
                    "description": "Шаблон для приглашения на встречу",
                    "text": (
                        "Привет! 🤝\n\n"
                        "Предлагаю встретиться {когда} чтобы обсудить {тема}.\n\n"
                        "Место: {место}\n\n"
                        "Подтверди пожалуйста удобно ли тебе."
                    )
                },
                {
                    "keyword": "НАПОМИНАНИЕ",
                    "name": "Напоминание",
                    "description": "Общее напоминание",
                    "text": (
                        "⏰ Напоминаю:\n\n"
                        "{текст}\n\n"
                        "Срок: {срок}"
                    )
                },
                {
                    "keyword": "СПАСИБО",
                    "name": "Благодарность",
                    "description": "Простая благодарность",
                    "text": (
                        "Спасибо большое за {за_что}! 🙏\n"
                        "Очень ценю твою помощь."
                    )
                }
            ]
        }
        self.templates_file.parent.mkdir(parents=True, exist_ok=True)
        self.templates_file.write_text(
            json.dumps(example, ensure_ascii=False, indent=2),
            encoding="utf-8"
        )
        log.info(f"✅ Создан пример шаблонов: {self.templates_file}")

    def find(self, keyword: str) -> Optional[Template]:
        """Ищет шаблон по кодовому слову (регистронезависимо)."""
        return self.templates.get(keyword.upper())

    def find_in_text(self, text: str) -> Optional[tuple[Template, str]]:
        """
        Ищет кодовое слово в тексте.
        Возвращает (шаблон, кодовое_слово) или None.
        """
        upper = text.upper()
        for keyword, template in self.templates.items():
            if keyword in upper:
                return template, keyword
        return None

    def list_all(self) -> str:
        """Возвращает список всех шаблонов для отображения."""
        if not self.templates:
            return "📭 Шаблоны не найдены. Добавь их в config/templates.json"

        lines = ["📋 **Доступные шаблоны:**\n"]
        for kw, t in self.templates.items():
            vars_str = ", ".join(f"{{{v}}}" for v in t.variables) if t.variables else "нет переменных"
            lines.append(f"• `{kw}` — {t.name}")
            lines.append(f"  Переменные: {vars_str}")
            if t.description:
                lines.append(f"  {t.description}")
            lines.append("")
        return "\n".join(lines)

    def reload(self):
        """Перезагружает шаблоны из файла (без перезапуска)."""
        self.templates = {}
        self._load()
        log.info("🔄 Шаблоны перезагружены")

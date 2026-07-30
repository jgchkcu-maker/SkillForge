<div align="center">

# SkillForge

### Локальный установщик AI-скиллов для разработчиков

<p>Устанавливайте переносимые <code>SKILL.md</code>-воркфлоу в Kilo Code, Codex, Claude Code, Gemini CLI и другие совместимые инструменты — из одного понятного рабочего пространства.</p>

<p>
  <img src="docs/skillforge-banner.png" alt="SkillForge — локальное управление AI-скиллами" width="100%">
</p>

<p>
  <a href="https://github.com/jgchkcu-maker/SkillForge/stargazers"><img src="https://img.shields.io/github/stars/jgchkcu-maker/SkillForge?style=flat-square&color=7c5cff" alt="Звёзды GitHub"></a>
  <a href="https://github.com/jgchkcu-maker/SkillForge/issues"><img src="https://img.shields.io/github/issues/jgchkcu-maker/SkillForge?style=flat-square&color=00a896" alt="Issues"></a>
  <a href="https://github.com/jgchkcu-maker/SkillForge"><img src="https://img.shields.io/badge/local--first-без%20облачного%20аккаунта-111827?style=flat-square" alt="Локальная работа"></a>
  <a href="https://github.com/jgchkcu-maker/SkillForge/blob/main/README.md"><img src="https://img.shields.io/badge/status-active-00a896?style=flat-square" alt="Активный проект"></a>
</p>

<p>
  <a href="#быстрый-старт">Быстрый старт</a> ·
  <a href="#как-это-работает">Как это работает</a> ·
  <a href="#поддерживаемые-инструменты">Инструменты</a> ·
  <a href="#участие-в-разработке">Разработка</a>
</p>

</div>

---

## Что делает SkillForge

SkillForge превращает установку скилла в короткий и прозрачный процесс:

| Найти | Выбрать | Установить | Проверить |
| --- | --- | --- | --- |
| Находит локальные проекты и AI-инструменты | Показывает только подходящие места установки | Копирует весь скилл вместе с ресурсами | Показывает прогресс и точную причину ошибки |

### Почему это удобно

- **Учитывает проект** — устанавливает скилл в выбранную рабочую папку.
- **Поддерживает несколько агентов** — один источник можно установить сразу в несколько инструментов.
- **Работает локально** — приложение запускается на `127.0.0.1`, облачный аккаунт не нужен.
- **Показывает процесс** — каждая операция сопровождается живым журналом.
- **Безопасен по умолчанию** — существующие скиллы не перезаписываются без явного разрешения.
- **Совместим** — использует открытый формат `SKILL.md`.

## Быстрый старт

### Требования

- Windows 10 или новее
- Python 3.10+
- Git

### 1. Скачайте репозиторий

```powershell
git clone https://github.com/jgchkcu-maker/SkillForge.git
cd SkillForge
```

### 2. Установите зависимости

```powershell
python -m pip install -r requirements.txt
```

### 3. Запустите SkillForge

Дважды нажмите [`start-skill-forge.bat`](start-skill-forge.bat) или выполните:

```powershell
.\start-skill-forge.bat
```

После запуска откройте <http://127.0.0.1:8765>.

## Установка первого скилла

1. Откройте страницу **Установка**.
2. Выберите готовую зелёную цель, например **Kilo Code**.
3. Вставьте URL Git-репозитория.
4. Выберите **этот проект** или **все проекты**.
5. Нажмите **Установить** и следите за журналом операции.

Если в репозитории несколько скиллов, укажите нужный через `#skill=`:

```text
https://github.com/bergside/awesome-design-skills.git#skill=codex
```

Результат появится здесь:

```text
<ваш-проект>/.kilo/skills/<имя-скилла>/SKILL.md
```

## Примеры источников

| Назначение | Источник |
| --- | --- |
| Frontend-дизайн | `https://github.com/vercel-labs/agent-skills.git#skill=frontend-design` |
| Проверка дизайна | `https://github.com/microsoft/skills.git#skill=frontend-design-review` |
| Разработка MCP-серверов | `https://github.com/microsoft/skills.git#skill=mcp-builder` |
| Планирование и анализ | `https://github.com/jMerta/codex-skills.git#skill=plan-work` |
| Вкус и визуальное качество | `https://github.com/Leonxlnx/taste-skill.git#skill=taste-skill` |

Перед установкой стороннего скилла всегда изучайте его `SKILL.md` и вложенные скрипты.

## Поддерживаемые инструменты

| Инструмент | В проекте | Глобально |
| --- | --- | --- |
| Kilo Code | `.kilo/skills` | `~/.kilo/skills` |
| OpenAI Codex | `.agents/skills` | `$CODEX_HOME/skills` |
| Claude Code | `.claude/skills` | `~/.claude/skills` |
| Gemini CLI | `.gemini/skills` | `~/.gemini/skills` |
| Cline | `.cline/skills` | `~/.cline/skills` |
| Roo Code | `.roo/skills` | `~/.roo/skills` |
| GitHub Copilot CLI | `.github/skills` | `~/.copilot/skills` |

Доступность зависит от конфигурации компьютера: цель отображается готовой только при обнаружении совместимого пути.

## Как это работает

```mermaid
flowchart LR
    A[Git-репозиторий или локальная папка] --> B[Подготовка источника]
    B --> C{Поиск SKILL.md}
    C -->|Один скилл| D[Выбор цели]
    C -->|Несколько скиллов| E[Выбор через #skill=NAME]
    E --> D
    D --> F[Копирование полного дерева]
    F --> G[Результат и обновление списка]
```

Flask-бэкенд отвечает за поиск, проверку, установку и потоковый журнал. React-интерфейс остаётся небольшим локальным пультом управления.

## Разработка

```powershell
# Бэкенд
python skill-forge/app.py

# Фронтенд в режиме разработки
cd skill-forge
pnpm install
pnpm dev

# Сборка фронтенда
pnpm build

# Тесты из корня репозитория
python -m unittest test_skillforge_agents.py
```

## Структура проекта

```text
SkillForge/
├── skill-forge/              # React-интерфейс и Flask API
│   ├── src/                  # Исходники фронтенда
│   └── app.py                # Локальный API и поток задач
├── agent_registry.py         # Цели и возможности агентов
├── artifact_installer.py     # Установка скиллов и MCP-артефактов
├── detector.py               # Поиск локальных инструментов
├── skill_installer.py        # Вспомогательная логика
├── start-skill-forge.bat     # Запуск в Windows
└── test_skillforge_agents.py # Интеграционные тесты
```

## Участие в разработке

Будем рады Issues и pull request’ам. Хорошее изменение содержит описание проблемы, небольшое целевое решение и способ проверки.

Не добавляйте в коммиты локальные `.kilo/`, `.kilocode/`, `node_modules/`, секреты и сгенерированные логи.

## Безопасность

SkillForge устанавливает инструкции из указанных вами источников. Считайте внешние скиллы недоверенными: проверяйте `SKILL.md`, вложенные скрипты и устанавливайте материалы только из источников, которым доверяете.

## Лицензия

Файл лицензии пока не добавлен. До публикации лицензии все права остаются у владельца репозитория.

<div align="center">

Сделано для спокойной и переносимой разработки с AI.

</div>

# SkillForge

Красивый GUI-интерфейс для `skill_installer.py`.

## Запуск

Дважды кликните по файлу:

```
start-skill-forge.bat
```

Приложение откроется в браузере по адресу `http://127.0.0.1:8765`.

## Что внутри

- `skill-forge/app.py` — Flask backend на Python, обёртка над `skill_installer.py`
- `skill-forge/src/` — React-фронтенд (Vite + Tailwind + shadcn/ui)
- `start-skill-forge.bat` — лаунчер

## Сборка фронтенда

```bash
cd skill-forge
pnpm install
pnpm run build
```

## Перезапуск backend без батника

```bash
cd skill-forge
python app.py
```

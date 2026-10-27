# Расписание ИС-25-4
1. Залей все файлы в репозиторий (включая папку `.github`).
2. Settings → Pages → Deploy from a branch → `main` / `(root)`.
3. Settings → Secrets and variables → Actions → добавь `TG_TOKEN` и `TG_CHAT_ID`.
4. Actions → update-schedule → Run workflow. Дальше работает само.
Парсинг ячеек: `parse.py`. Названия, алиасы и преподаватели: `config.json`.

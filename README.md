# RDM Telegram Bot

Простой Telegram-бот для Redmine/RDM, который помогает заносить трудозатраты.

## Возможности

- выбор проекта;
- выбор задачи проекта;
- выбор часов: 1, 1.5, 2, 2.5 или 3;
- выбор даты, по умолчанию сегодня;
- выбор деятельности из Redmine;
- ввод комментария;
- отправка трудозатраты в Redmine через API.

## Настройка

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
Copy-Item .env.example .env
```

Заполните `.env`:

```env
BOT_TOKEN=telegram_bot_token
RDM_BASE_URL=https://rdm.example.com
RDM_API_KEY=redmine_api_key
```

## Запуск

```powershell
.\.venv\Scripts\python.exe bot.py
```

Или:

```powershell
.\run_bot.ps1
```

## Проверка Redmine API

```powershell
.\.venv\Scripts\python.exe check_rdm.py
```

PROJECTS_PER_PAGE = 10
ISSUES_PER_PAGE = 10
COMMENT_LIMIT = 1024
PROJECTS_LOAD_TIMEOUT_SECONDS = 8
IDLE_PROJECT_BUTTON_TEXT = "📂 Выбрать проект"
TRACKING_BUTTON_TEXT = "🚀 Tracking"
FAVORITE_PROJECTS_BUTTON_TEXT = "⭐ Избранные проекты"
FAVORITES_SETUP_BUTTON_TEXT = "⚙️ Настроить избранное"
LOGIN_BUTTON_TEXT = "🔐 Войти"
RECENT_ISSUES_BUTTON_TEXT = "🎫 Последние задачи"
RECENT_ISSUES_LIMIT = 10
FAVORITE_PROJECTS_LIMIT = 10
FAVORITE_PROJECTS_SETUP_LIMIT = 10000
DEFAULT_ACTIVITY_NAME = "Support"
BOT_PROFILE_SHORT_DESCRIPTION = (
    "Умный учёт времени в Redmine из Telegram: задачи, даты, деятельности и комментарии в пару шагов."
)
BOT_PROFILE_DESCRIPTION = (
    "RDM Time Tracker превращает учёт трудозатрат в Redmine в быстрый диалог в Telegram. "
    "Войдите по личному API key, выберите проект и задачу или просто отправьте номер задачи. "
    "Бот поможет указать время, дату, деятельность и комментарий, а затем отправит запись "
    "в Redmine от вашего имени."
)
START_TEXT_LOGGED_OUT = (
    "👋 Добро пожаловать в RDM Time Tracker\n\n"
    "Я помогаю аккуратно заносить трудозатраты в Redmine прямо из Telegram: без лишних вкладок, "
    "долгих переходов и ручного поиска.\n\n"
    "Вы сможете выбрать проект и задачу или сразу отправить номер задачи, указать время, дату, "
    "деятельность и комментарий. После подтверждения запись уйдет в Redmine от вашего имени.\n\n"
    "Для начала подключите свой Redmine-аккаунт: нажмите «🔐 Войти» и отправьте API key."
)
START_TEXT_LOGGED_IN = (
    "✨ Вы в рабочем режиме\n\n"
    "Нажмите «🚀 Tracking», настройте избранное через «⚙️ Настроить избранное» "
    "или просто отправьте номер задачи, например 7875. Я сразу перейду к списанию времени."
)

from aiogram.fsm.state import State, StatesGroup


class TimeEntryFlow(StatesGroup):
    choosing_project = State()
    choosing_issue = State()
    choosing_hours = State()
    entering_hours = State()
    choosing_date = State()
    choosing_activity = State()
    writing_comment = State()
    confirming = State()

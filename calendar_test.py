import os
from datetime import datetime, timedelta, time
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build

# 🔐 Подключение к API
SCOPES = ['https://www.googleapis.com/auth/calendar']
creds = Credentials.from_service_account_file('credentials_calendar.json', scopes=SCOPES)
service = build('calendar', 'v3', credentials=creds)

# 📅 Настройки
calendar_id = 'primary'  # Или вставь ID созданного календаря (если не основной)
days_ahead = 7
slot_duration_minutes = 30

work_start = time(8, 0)
work_end = time(18, 0)

def is_weekday(date_obj):
    return date_obj.weekday() < 5  # Пн–Пт (0–4)

def get_busy_slots(start_dt, end_dt):
    body = {
        "timeMin": start_dt.isoformat() + "Z",
        "timeMax": end_dt.isoformat() + "Z",
        "timeZone": "Europe/Warsaw",
        "items": [{"id": calendar_id}]
    }
    events_result = service.freebusy().query(body=body).execute()
    return events_result['calendars'][calendar_id]['busy']

def get_free_slots():
    now = datetime.utcnow()
    end_range = now + timedelta(days=days_ahead)
    busy = get_busy_slots(now, end_range)

    free_slots = []

    current = datetime.combine(now.date(), work_start)
    while current.date() <= end_range.date():
        if is_weekday(current):
            end_time = datetime.combine(current.date(), work_end)
            while current + timedelta(minutes=slot_duration_minutes) <= end_time:
                slot_start = current
                slot_end = current + timedelta(minutes=slot_duration_minutes)

                overlapping = any(
                    slot_start < datetime.fromisoformat(b["end"]) and slot_end > datetime.fromisoformat(b["start"])
                    for b in busy
                )

                if not overlapping:
                    free_slots.append((slot_start, slot_end))

                current += timedelta(minutes=slot_duration_minutes)
        current = datetime.combine(current.date() + timedelta(days=1), work_start)

    return free_slots

# 🧪 Выводим
if __name__ == "__main__":
    slots = get_free_slots()
    print("📆 Свободные слоты:")
    for start, end in slots:
        print(f"{start.strftime('%Y-%m-%d %H:%M')} — {end.strftime('%H:%M')}")

# 🤖 Car Service Bot

A Telegram bot for an auto repair service with integration into **Google Sheets** and **Google Calendar**.  
Allows clients to book appointments, receive announcements, view promotions, and interact with an AI assistant for diagnostics.

---

## 🚀 Features

- 🌐 Multilingual support: Russian and Polish
- 📅 Google Calendar integration — select available time slots
- 📊 Google Sheets CRM integration (requests, history, parts)
- 🧠 AI assistant for error codes and symptoms (ChatGPT)
- 📍 Send location and route buttons
- 📢 Admin-controlled newsletter broadcasts
- 🔔 Telegram notifications for new client requests
- 🐳 Dockerized deployment with monitoring

---

## 📦 Installation

```bash
git clone https://github.com/yaromindzmitry/car-service-bot.git
cd car-service-bot
cp .env.example .env
# Edit .env and credentials.json
docker compose up -d
```

---

## ⚙️ Environment Variables

Create a `.env` file based on the following template:

```env
BOT_TOKEN=your-telegram-bot-token
OPENAI_API_KEY=your-OPENAI_API-token
GOOGLE_SHEET_ID=your-google-sheet-id
GOOGLE_CREDENTIALS_PATH=your-CREDENTIALS.json
GOOGLE_CREDENTIALS_CALENDAR=c  .json
CALENDAR_ID=your-calendar-id
ADMIN_CHAT_ID=your-admin-id
LANGUAGES=ru,pl,en
```

---

## 🧠 AI Assistant

The bot collects:
- Make, model, year, engine capacity, and fuel type
- Symptoms or error codes
- Provides potential causes or requests external data for known codes

---

## 🗂️ Google Sheets CRM Structure

- `Zlecenia` — requests from the bot
- `Подписчики` — telegram-bot subscribers
- `Акции` - promotions and news for clients
- `Контакты` - service contacts: phone, Instagram, Facebook, Google Maps coordinates

---

## 🧾 UI Examples

### Multilingual start menu:
![Main menu](assets/screenshots/bot-main-menu.png)

### AI diagnostics flow:
![AI assistant](assets/screenshots/ai-diagnostics.png)

---

## 📊 Grafana Monitoring

Bot and infrastructure are monitored with **Prometheus + Grafana**.

### 🧱 Container metrics (cAdvisor)
![Container Metrics (cAdvisor)](assets/screenshots/Снимок%20экрана%202025-05-04%20в%2014.09.47.png)

### 🐳 Docker Monitoring Dashboard
![Docker Monitoring](assets/screenshots/Снимок%20экрана%202025-05-04%20в%2014.10.31.png)

### 🖥️ Node Exporter Full
![Node Exporter Full](assets/screenshots/Снимок%20экрана%202025-05-04%20в%2014.11.03.png)

---

## 🐳 Docker Compose

```yaml
version: '3.8'

services:
  bot:
    build: .
    container_name: car_service_bot
    restart: always
    env_file:
      - .env
    volumes:
      - ./credentials.json:/app/credentials.json
```

---

## 📬 Notifications and Alerts

- Admin receives a message when a new request is submitted
- Telegram alerts via Prometheus when CPU or RAM thresholds are exceeded

---

## 📄 License

Project is licensed under the [MIT License](LICENSE)

---

## 💬 Contact

Author: [Dzmitry Yaromin](https://github.com/yaromindzmitry)  
Telegram: [@MPCBimmerUpdate](https://t.me/MPCBimmerUpdate)

---

## 🛠 Technologies & Skills

### Languages & Frameworks:
- Python (asyncio, `aiogram`)
- JavaScript (for Google Sheets frontend logic, if applicable)

### APIs & Integrations:
- Telegram Bot API (`aiogram`)
- Google Sheets API
- Google Calendar API
- OpenAI API (ChatGPT)

### DevOps & Infrastructure:
- Docker & Docker Compose
- Prometheus + Grafana (monitoring)
- Node Exporter, cAdvisor
- Telegram alerts via Prometheus
- LXD containers (Ubuntu server on NAS)

### Other Skills:
- Multi-language input validation and UX in Telegram
- Secure handling of `.env` and `credentials.json`
- Google automation for CRM and scheduling
- Git + GitHub (project structure and collaboration)

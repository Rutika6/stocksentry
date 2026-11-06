# StockSentry — Smart Stock Alert

A web app that helps small shops and student organizations avoid running out of supplies.
Track products, set minimum levels, get low-stock flags, and export a restocking list.

**Stack:** Python · Flask · SQLite · Gunicorn · Docker · AWS EC2

## Features

- Dashboard with KPIs, stock-health donut chart, per-category status and recent activity
- Add / edit / delete products (SKU, category, supplier, unit, price, minimum level)
- Automatic **Low** and **Out** flags, with a one-click `+` / `−` quick stock adjust
- **Restock list** grouped by supplier, with suggested order quantity and estimated cost
- Export restock list and full inventory to **CSV**; import products from CSV
- Activity log (audit trail) of every stock change
- Optional **Telegram alerts** when an item drops below its minimum
- **Multi-user with roles** (Admin, Manager, Staff, Viewer), sign-up, hashed passwords, password change
- **Team page** (admin): add users, change roles, disable, reset passwords, delete
- **Restock orders:** create an order per supplier from the restock list, then mark it received and stock updates automatically
- Every activity-log entry records **who** made the change
- CSRF protection, login brute-force lock, CSV-injection guard, dark / light theme, mobile friendly

## Roles

| Can… | Admin | Manager | Staff | Viewer |
|---|:-:|:-:|:-:|:-:|
| View dashboard, inventory, activity, restock list | ✔ | ✔ | ✔ | ✔ |
| Use stock (decrease quantity) | ✔ | ✔ | ✔ | |
| Add stock, add / edit products, import CSV | ✔ | ✔ | | |
| Create and receive restock orders | ✔ | ✔ | | |
| Delete products | ✔ | | | |
| Manage team members and roles | ✔ | | | |

The first admin is created from `ADMIN_USER` / `ADMIN_PASSWORD` in `.env`. People who sign up themselves start as **Viewer**;
an admin upgrades them on the **Team** page. Set `ALLOW_SIGNUP=0` to turn public sign-up off.

## Run locally (no Docker)

```powershell
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
python app.py
```
Open http://localhost:5000 — login `admin` / `admin123`, click **Load demo data**, then open **Team → Add demo team** to try every role
(`manager1`, `staff1`, `viewer1`, password `Demo@1234`; delete them before going public).

## Run with Docker

```powershell
copy .env.example .env        # then edit SECRET_KEY and ADMIN_PASSWORD
docker compose up -d --build
```
Open http://localhost (port 80). Data lives in the `stocksentry-data` volume, so it survives restarts.

Useful commands:
```
docker compose ps          # status (shows "healthy")
docker compose logs -f     # live logs
docker compose down        # stop (data is kept)
```

## Deploy on AWS EC2

1. Launch an **Ubuntu 22.04/24.04**, `t2.micro` / `t3.micro` (Free Tier) instance. Create and download a key pair (`.pem`).
2. Security group inbound rules: **SSH (22)** from *My IP*, **HTTP (80)** from anywhere.
3. Connect: `ssh -i your-key.pem ubuntu@<EC2-PUBLIC-IP>`
4. Install Docker:
   ```bash
   curl -fsSL https://get.docker.com | sudo sh
   sudo usermod -aG docker ubuntu && newgrp docker
   ```
5. Get the code onto the server (`git clone <your-repo>` or `scp`), then:
   ```bash
   cd stocksentry
   cp .env.example .env && nano .env     # set SECRET_KEY and ADMIN_PASSWORD
   docker compose up -d --build
   ```
6. Open `http://<EC2-PUBLIC-IP>` in your browser.

**Cost safety:** stop the instance when not demoing, and keep an AWS Budget alert active.

## Telegram alerts (optional)

1. In Telegram, talk to **@BotFather** → `/newbot` → copy the token.
2. Send any message to your bot, then open `https://api.telegram.org/bot<TOKEN>/getUpdates` and copy `chat.id`.
3. Put both in `.env` as `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID`, then restart the container.
4. A **Send alert** button appears, and alerts also fire automatically when an item newly drops to Low/Out.

## CSV import format

```
name,sku,category,supplier,unit,quantity,min_level,price
A4 Paper Ream,STA-001,Stationery,PaperHub,reams,4,10,280
```
Rows with an existing SKU update that product; new SKUs are added.

## Project layout

```
app.py              Flask app, routes, SQLite access
templates/          Jinja2 pages (dashboard, inventory, restock, orders, team, activity, account, login, register)
static/             style.css, app.js (filtering, sorting, quick adjust, chart)
Dockerfile          Container image (gunicorn, non-root user, healthcheck)
docker-compose.yml  Service + persistent volume
```

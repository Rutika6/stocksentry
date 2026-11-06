# 📦 StockSentry – Smart Stock Alert

**A Smart Inventory Management System with Automated Low-Stock Alerts**

StockSentry is a web-based inventory management application designed for small businesses, shops, and student organizations. It helps users manage products, monitor stock levels, identify low-stock items, and plan restocking efficiently.

The main goal is to reduce manual inventory work, prevent stock shortages, and make product management easier.

## 🚀 Features

- **Dashboard:** View total products, low-stock items, out-of-stock items, and inventory statistics.
- **Product Management:** Add, edit, delete, and manage product details.
- **Automatic Stock Alerts:** Identify products that have reached or fallen below their minimum stock level.
- **Restock Suggestions:** Calculate suggested restocking quantities and estimated costs.
- **Supplier Management:** Organize restocking requirements by supplier.
- **Restock Orders:** Create supplier orders and update inventory automatically when orders are received.
- **Activity History:** Maintain a record of stock changes and the users responsible.
- **User Authentication:** Secure login, registration, and password management.
- **Role-Based Access Control:** Support Admin, Manager, Staff, and Viewer roles.
- **CSV Import and Export:** Import product records and export inventory and restocking information.
- **Telegram Notifications:** Optional alerts for low-stock products.
- **Responsive Interface:** User-friendly interface with dark and light themes.

## 🛠️ Technologies Used

| Technology | Purpose |
|---|---|
| Python | Backend programming and application logic |
| Flask | Backend web framework |
| SQLite | Relational database |
| HTML5 | Webpage structure |
| CSS3 | Styling and responsive layout |
| JavaScript | Frontend interactions |
| Jinja2 | Dynamic HTML templates |
| Gunicorn | Python application server |
| Docker | Application containerization |
| AWS EC2 | Cloud deployment option |
| Telegram Bot API | Optional stock notifications |

## ⚙️ How It Works

1. Users log in to the application.
2. They add products with details such as name, SKU, category, supplier, quantity, and minimum stock level.
3. The system monitors product quantities.
4. When stock reaches the minimum level, the product is marked as Low or Out.
5. The application generates restocking suggestions.
6. Users can create supplier orders.
7. When an order is received, the corresponding stock quantity is updated automatically.
8. All important stock changes are recorded in the activity history.

## 👥 User Roles

| Role | Permissions |
|---|---|
| Admin | Full access, including product and user management |
| Manager | Manage products, stock, and restock orders |
| Staff | View inventory and decrease stock |
| Viewer | Read-only access |

## 🗄️ Database

StockSentry uses **SQLite** to store application data.

The main database tables are:

- `users` – Stores user accounts, roles, and authentication details.
- `products` – Stores product information and available quantities.
- `movements` – Records inventory changes and activity history.
- `orders` – Stores supplier restocking orders.
- `order_items` – Stores products and quantities included in each order.

## 💻 Installation and Setup

### Prerequisites

- Python 3.10 or later
- pip (Python package manager)
- Git

### Step 1: Clone the repository

```bash
git clone YOUR_GITHUB_REPOSITORY_URL
```

### Step 2: Navigate to the project folder

```bash
cd StockSentry
```

### Step 3: Create a virtual environment

```bash
python -m venv venv
```

### Step 4: Activate the virtual environment

**Windows:**

```bash
venv\Scripts\activate
```

**Mac/Linux:**

```bash
source venv/bin/activate
```

### Step 5: Install dependencies

```bash
pip install -r requirements.txt
```

### Step 6: Run the application

```bash
python app.py
```

### Step 7: Open in your browser

```text
http://localhost:5000
```

The application initializes its SQLite database automatically.

For a fresh local installation, the default development login is:

- Username: `admin`
- Password: `admin123`

Change the default credentials before using the application outside a local demo.

## 🐳 Docker Support

The project also supports Docker for containerized execution.

Create your environment file:

```bash
copy .env.example .env
```

Edit the environment variables, then run:

```bash
docker compose up -d --build
```

Open:

```text
http://localhost
```

## ☁️ Cloud Deployment

The project includes Docker-based deployment configuration for AWS EC2.

An EC2 virtual machine can host the application, making it accessible through a public IP address.

## 🔐 Security Features

- Password hashing
- Session-based authentication
- Role-based permissions
- CSRF protection
- Login brute-force protection
- Secure response headers
- CSV formula-injection protection

**Security note:** Never upload your `.env` file, real passwords, API tokens, or private credentials to GitHub.

## 📁 Project Structure

```text
StockSentry/
│
├── app.py
├── requirements.txt
├── README.md
├── .gitignore
├── .env.example
├── Dockerfile
├── docker-compose.yml
│
├── data/
│   └── stocksentry.db
│
├── static/
│   ├── app.js
│   └── style.css
│
└── templates/
    ├── dashboard.html
    ├── inventory.html
    ├── restock.html
    ├── orders.html
    ├── users.html
    ├── history.html
    ├── account.html
    ├── login.html
    └── register.html
```

## 🔮 Future Enhancements

- Integration with a React-based frontend.
- Advanced inventory analytics and reporting.
- Integration with additional supplier management systems.
- Improved demand forecasting.
- Barcode and QR code-based product scanning.
- More notification channels.

## 🎯 Project Objective

StockSentry aims to simplify inventory management by providing real-time stock monitoring, automated low-stock identification, and organized restocking workflows.

It can be

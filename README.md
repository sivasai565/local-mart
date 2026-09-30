# LocalMart

LocalMart is a Flask-based local commerce and inventory management prototype for villages and small towns. It connects local customers with nearby shop owners, allows product discovery, cart checkout, COD/UPI flows, and stock management.

## Features

- Customer login and registration
- Shop owner login and registration
- Local product search and listing
- Cart and checkout flow
- COD and UPI payment simulation with backend verification support
- Order tracking for customers
- Owner dashboard and inventory management
- Auto stock reduction after successful order placement
- Expiry checks and stock visibility rules
- SQLite database for persistence

## Tech Stack

- Python Flask
- SQLite
- Bootstrap 5
- HTML/CSS/JavaScript

## Project Structure

```text
localmart/
├── app.py
├── requirements.txt
├── .env
├── .gitignore
├── database/
│   └── localmart.db
├── static/
│   ├── css/
│   ├── js/
│   └── uploads/
├── templates/
│   ├── add_product.html
│   ├── base.html
│   ├── cart.html
│   ├── checkout.html
│   ├── customer_dashboard.html
│   ├── customer_login.html
│   ├── customer_register.html
│   ├── index.html
│   ├── orders.html
│   ├── owner_dashboard.html
│   ├── owner_login.html
│   ├── owner_orders.html
│   ├── owner_register.html
│   ├── payment.html
│   ├── product_details.html
│   ├── profile.html
│   ├── stock.html
│   └── owner_register.html
└── README.md
```

## Setup

1. Create a virtual environment:

```bash
python -m venv .venv
```

2. Activate it:

- Windows PowerShell:

```powershell
.\.venv\Scripts\Activate.ps1
```

- Windows Command Prompt:

```cmd
.venv\Scripts\activate.bat
```

3. Install dependencies:

```bash
pip install -r requirements.txt
```

4. Start the app:

```bash
python app.py
```

The app runs at: http://localhost:5000

## Default Demo Accounts

Customer:
- Email: customer@localmart.com
- Password: admin123

Shop owner:
- Email: owner@localmart.com
- Password: admin123

## First Customer

Register a new customer from the homepage or use the default test customer.

## First Shop Owner

Register a shop owner account from the Shop Owner Login page.

## Add Products

Login as the owner and go to the dashboard, then click Add Product / Add Stock.

## Test an Order

1. Login as the customer.
2. Search for products.
3. Add a product to the cart.
4. Proceed to checkout.
5. Place the order and select COD or UPI.

## Test Stock Reduction

Purchase a product from the customer dashboard. The app reduces available stock automatically and updates sold quantity.

## Payment Setup

The code supports UPI verification using a configured gateway endpoint in `.env`.

For UPI app payments and owner UTR notifications, configure these values in the
deployment environment. `SYSTEM_PASSWORD` must be a Gmail App Password, not the
normal Gmail password:

```env
SYSTEM_EMAIL=your-email@gmail.com
SYSTEM_PASSWORD=your-gmail-app-password
```

The frontend uses same-origin API URLs, so no Gmail credential is sent to the browser.
Submitting a UTR records it as `PAYMENT_SUBMITTED`; it is only a customer-provided
reference and must be checked against the owner's bank statement.

If the frontend is hosted separately, set `FRONTEND_ORIGIN` to its exact HTTPS origin.
The API then allows only that origin and enables secure session cookies.

Example:

```env
UPI_GATEWAY_URL=https://example-payment-gateway.com/api/verify
```

If no URL is configured, the app falls back to a demo verification check.

## Deployment

To deploy online:

1. Use a VPS or cloud platform such as Render, Railway, or PythonAnywhere.
2. Set environment variables securely.
3. Use a production WSGI server such as Gunicorn.
4. Run the application with a proper reverse proxy and HTTPS.

SQLite data is stored in `database/localmart.db` by default and is not reset when
the app starts. The `users`, `shops`, `products`, `orders`, and `payments` rows are
kept across restarts. On a hosting provider with ephemeral storage, set
`DATABASE_PATH` to a mounted persistent-disk path or use a managed database such as
PostgreSQL; otherwise the provider can discard the SQLite file during redeploys.

Example:

```bash
pip install gunicorn
gunicorn -w 4 app:app
```

## Notes

This is a prototype and is designed for learning and demo purposes. Real-world production should add:

- proper multi-user roles and permissions
- stronger payment provider integration
- email verification
- production-grade database backend such as PostgreSQL
- stronger security, backups, and deployment hardening

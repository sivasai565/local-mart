import os
import re
import smtplib
import sqlite3
import uuid
from datetime import datetime
from email.message import EmailMessage
from urllib import parse as urllib_parse
from urllib import request as urllib_request

from flask import (
    Flask,
    flash,
    redirect,
    render_template,
    request,
    session,
    url_for,
)

from werkzeug.security import check_password_hash, generate_password_hash
from werkzeug.utils import secure_filename


# ============================================================
# FLASK CONFIGURATION
# ============================================================

app = Flask(__name__)

app.config["SECRET_KEY"] = os.getenv(
    "SECRET_KEY",
    "localmart-dev-secret-key"
)

app.config["UPLOAD_FOLDER"] = os.path.join(
    app.root_path,
    "static",
    "uploads"
)

os.makedirs(app.config["UPLOAD_FOLDER"], exist_ok=True)


# ============================================================
# DATABASE CONFIGURATION
# ============================================================

DB_PATH = os.path.join(
    app.root_path,
    "database",
    "localmart.db"
)

os.makedirs(
    os.path.dirname(DB_PATH),
    exist_ok=True
)


def get_db():
    """
    Create a SQLite database connection.

    WAL mode is NOT enabled on every connection because doing so
    repeatedly can contribute to database locking.
    """

    conn = sqlite3.connect(
        DB_PATH,
        timeout=30,
        check_same_thread=False
    )

    conn.row_factory = sqlite3.Row

    conn.execute(
        "PRAGMA busy_timeout = 30000"
    )

    conn.execute(
        "PRAGMA foreign_keys = ON"
    )

    return conn


def ensure_shop_payment_columns():

    conn = get_db()
    columns = conn.execute(
        "PRAGMA table_info(shops)"
    ).fetchall()
    existing = {column[1] for column in columns}

    for column_name, column_sql in [
        ("asorpay_upi_id", "TEXT"),
        ("asorpay_qr_code", "TEXT"),
    ]:
        if column_name not in existing:
            conn.execute(
                f"ALTER TABLE shops ADD COLUMN {column_name} {column_sql}"
            )

    conn.commit()
    conn.close()


# ============================================================
# DATABASE INITIALIZATION
# ============================================================

def init_db():

    conn = sqlite3.connect(
        DB_PATH,
        timeout=30
    )

    conn.row_factory = sqlite3.Row

    conn.execute(
        "PRAGMA busy_timeout = 30000"
    )

    conn.execute(
        "PRAGMA foreign_keys = ON"
    )

    # Enable WAL only during database initialization.
    conn.execute(
        "PRAGMA journal_mode = WAL"
    )

    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            email TEXT NOT NULL UNIQUE,
            password_hash TEXT NOT NULL,
            mobile TEXT,
            address TEXT,
            village TEXT,
            pin_code TEXT,
            user_type TEXT NOT NULL,
            shop_id INTEGER,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS shops (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            shop_name TEXT NOT NULL,
            owner_name TEXT NOT NULL,
            email TEXT NOT NULL UNIQUE,
            mobile TEXT,
            address TEXT,
            village TEXT,
            pin_code TEXT,
            delivery_radius INTEGER DEFAULT 5,
            delivery_charge REAL DEFAULT 20,
            delivery_time TEXT DEFAULT 'Today, 5:00 PM - 7:00 PM',
            available_delivery_areas TEXT DEFAULT 'Village and nearby town',
            asorpay_upi_id TEXT,
            asorpay_qr_code TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS products (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            shop_id INTEGER NOT NULL,
            name TEXT NOT NULL,
            category TEXT NOT NULL,
            brand TEXT,
            manufacturer TEXT,
            description TEXT,
            image TEXT,
            price REAL NOT NULL,
            original_stock INTEGER NOT NULL,
            available_stock INTEGER NOT NULL,
            sold_quantity INTEGER DEFAULT 0,
            manufacturing_date TEXT,
            expiry_date TEXT,
            delivery_info TEXT,
            delivery_charge REAL DEFAULT 20,
            low_stock_threshold INTEGER DEFAULT 5,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,

            FOREIGN KEY(shop_id)
                REFERENCES shops(id)
        );

        CREATE TABLE IF NOT EXISTS orders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            order_reference TEXT NOT NULL,
            customer_id INTEGER NOT NULL,
            shop_id INTEGER NOT NULL,
            product_id INTEGER NOT NULL,
            quantity INTEGER NOT NULL,
            amount REAL NOT NULL,
            delivery_address TEXT,
            village TEXT,
            pin_code TEXT,
            order_date TEXT DEFAULT CURRENT_DATE,
            delivery_date TEXT,
            order_status TEXT DEFAULT 'Order Placed',
            payment_method TEXT DEFAULT 'COD',
            payment_status TEXT DEFAULT 'Pending',
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,

            FOREIGN KEY(customer_id)
                REFERENCES users(id),

            FOREIGN KEY(shop_id)
                REFERENCES shops(id),

            FOREIGN KEY(product_id)
                REFERENCES products(id)
        );

        CREATE TABLE IF NOT EXISTS payments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            order_reference TEXT NOT NULL,
            payment_method TEXT NOT NULL,
            transaction_id TEXT,
            amount REAL NOT NULL,
            payment_status TEXT DEFAULT 'Pending',
            payment_date TEXT DEFAULT CURRENT_TIMESTAMP
        );
        """
    )

    conn.commit()
    conn.close()

    ensure_shop_payment_columns()
    seed_demo_data()


# ============================================================
# DEMO DATA
# ============================================================

def seed_demo_data():

    conn = get_db()

    # --------------------------------------------------------
    # CUSTOMER
    # --------------------------------------------------------

    existing_customer = conn.execute(
        """
        SELECT id
        FROM users
        WHERE email = ?
        AND user_type = 'customer'
        """,
        ("customer@localmart.com",)
    ).fetchone()

    if not existing_customer:

        customer_password = generate_password_hash(
            "admin123"
        )

        conn.execute(
            """
            INSERT INTO users (
                name,
                email,
                password_hash,
                mobile,
                address,
                village,
                pin_code,
                user_type
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, 'customer')
            """,
            (
                "Rahul Verma",
                "customer@localmart.com",
                customer_password,
                "9876543210",
                "Main Road, Ward 2",
                "Vandana Village",
                "123456",
            )
        )

    # --------------------------------------------------------
    # SHOP
    # --------------------------------------------------------

    existing_shop = conn.execute(
        """
        SELECT id
        FROM shops
        WHERE email = ?
        """,
        ("owner@localmart.com",)
    ).fetchone()

    if existing_shop:

        shop_id = existing_shop["id"]

    else:

        shop_id = conn.execute(
            """
            INSERT INTO shops (
                shop_name,
                owner_name,
                email,
                mobile,
                address,
                village,
                pin_code,
                delivery_radius,
                delivery_charge,
                delivery_time,
                available_delivery_areas
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "Sri Lakshmi General Store",
                "Ramesh Kumar",
                "owner@localmart.com",
                "9123456780",
                "Market Street, Near Bus Stand",
                "Vandana Village",
                "123456",
                8,
                20,
                "Today, 5:00 PM - 7:00 PM",
                "Vandana Village and nearby areas",
            )
        ).lastrowid

    # --------------------------------------------------------
    # OWNER
    # --------------------------------------------------------

    existing_owner = conn.execute(
        """
        SELECT id
        FROM users
        WHERE email = ?
        AND user_type = 'owner'
        """,
        ("owner@localmart.com",)
    ).fetchone()

    if not existing_owner:

        owner_password = generate_password_hash(
            "admin123"
        )

        conn.execute(
            """
            INSERT INTO users (
                name,
                email,
                password_hash,
                mobile,
                address,
                village,
                pin_code,
                user_type,
                shop_id
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, 'owner', ?)
            """,
            (
                "Ramesh Kumar",
                "owner@localmart.com",
                owner_password,
                "9123456780",
                "Market Street",
                "Vandana Village",
                "123456",
                shop_id,
            )
        )

    conn.commit()
    conn.close()


# ============================================================
# LOGIN HELPERS
# ============================================================

def ensure_logged_in(role=None):

    if "user_id" not in session:

        flash(
            "Please log in to continue.",
            "error"
        )

        return False

    if role and session.get("user_type") != role:

        flash(
            "You do not have access to that page.",
            "error"
        )

        return False

    return True


def get_user_from_session():

    user_id = session.get("user_id")

    if not user_id:
        return None

    conn = get_db()

    user = conn.execute(
        """
        SELECT *
        FROM users
        WHERE id = ?
        """,
        (user_id,)
    ).fetchone()

    conn.close()

    return user


# ============================================================
# PRODUCT HELPERS
# ============================================================

def get_product_by_id(product_id):

    conn = get_db()

    product = conn.execute(
        """
        SELECT
            p.*,
            s.shop_name,
            s.delivery_radius,
            s.village AS shop_village,
            s.mobile AS shop_mobile,
            s.address AS shop_address,
            s.asorpay_upi_id,
            s.asorpay_qr_code

        FROM products p

        INNER JOIN shops s
            ON s.id = p.shop_id

        WHERE p.id = ?
        """,
        (product_id,)
    ).fetchone()

    conn.close()

    return product


def get_stock_status(product):

    if product is None:
        return "Unavailable"

    if product["expiry_date"]:

        try:

            expiry_date = datetime.strptime(
                product["expiry_date"],
                "%Y-%m-%d"
            ).date()

            if expiry_date <= datetime.now().date():
                return "Expired"

        except ValueError:
            pass

    if product["available_stock"] <= 0:
        return "Out of Stock"

    if product["available_stock"] <= product["low_stock_threshold"]:
        return "Low Stock"

    return "Available"


def product_is_available(product):

    if product is None:
        return False

    if product["available_stock"] <= 0:
        return False

    if product["expiry_date"]:

        try:

            expiry_date = datetime.strptime(
                product["expiry_date"],
                "%Y-%m-%d"
            ).date()

            if expiry_date <= datetime.now().date():
                return False

        except ValueError:
            pass

    return True


def estimate_delivery_distance_km(shop, customer):

    if not shop or not customer:
        return 8

    shop_village = (shop["village"] or "").strip().lower()
    customer_village = (customer["village"] or "").strip().lower()
    shop_pin = (shop["pin_code"] or "").strip()
    customer_pin = (customer["pin_code"] or "").strip()

    if shop_village and customer_village:
        if shop_village == customer_village:
            return 2

        common_words = set(shop_village.split()) & set(customer_village.split())
        if common_words:
            return 5

    if shop_pin and customer_pin and shop_pin == customer_pin:
        return 7

    return 12


def calculate_delivery_charge(shop, customer):

    distance_km = estimate_delivery_distance_km(shop, customer)

    if distance_km <= 8:
        return 20.0

    extra_km = max(0, distance_km - 8)
    return round(20.0 + (extra_km * 5.0), 2)


def get_stock_status_text(product):

    if product is None:
        return "Out of Stock"

    if product["available_stock"] <= 0:
        return "Out of Stock"

    if product["available_stock"] <= product["low_stock_threshold"]:
        return "Low Stock"

    return "In Stock"


def send_order_email(subject, body, recipient_email):

    smtp_host = os.getenv("SMTP_SERVER")
    if not smtp_host:
        print(f"EMAIL TO {recipient_email}\nSubject: {subject}\n{body}\n")
        return True

    try:
        msg = EmailMessage()
        msg["Subject"] = subject
        msg["From"] = os.getenv("MAIL_FROM", "noreply@localmart.com")
        msg["To"] = recipient_email
        msg.set_content(body)

        with smtplib.SMTP(
            smtp_host,
            int(os.getenv("SMTP_PORT", "587"))
        ) as server:
            if os.getenv("SMTP_USERNAME") and os.getenv("SMTP_PASSWORD"):
                server.starttls()
                server.login(
                    os.getenv("SMTP_USERNAME"),
                    os.getenv("SMTP_PASSWORD")
                )
            server.send_message(msg)

        return True

    except Exception as error:
        print(f"Email error for {recipient_email}: {error}")
        return False


def send_order_notifications(order_reference, customer, shop, rows):

    if not customer or not shop:
        return

    line_items = []
    for row in rows:
        line_items.append(
            f"- {row['product_name']} x {row['quantity']} ({row['amount']})"
        )

    order_total = sum(float(row["amount"]) for row in rows)

    customer_body = (
        "Your LocalMart order has been placed.\n\n"
        f"Order: {order_reference}\n"
        f"Shop: {shop['shop_name']}\n"
        "Order Items:\n"
        + "\n".join(line_items)
        + f"\n\nTotal Amount: ₹{order_total:.2f}\n"
        + "Status: Your order is now with the shop for confirmation."
    )

    owner_body = (
        "You have a new LocalMart order.\n\n"
        f"Order: {order_reference}\n"
        f"Customer: {customer['name']} ({customer['email']})\n"
        f"Phone: {customer['mobile']}\n"
        f"Address: {customer['address']}, {customer['village']}, {customer['pin_code']}\n"
        f"Shop: {shop['shop_name']}\n"
        + "Products:\n"
        + "\n".join(line_items)
        + f"\n\nTotal Amount: ₹{order_total:.2f}"
    )

    send_order_email(
        f"Your LocalMart order {order_reference} is confirmed",
        customer_body,
        customer["email"],
    )

    send_order_email(
        f"New LocalMart order received: {order_reference}",
        owner_body,
        shop["email"],
    )


def get_shop_by_user(user_id):

    conn = get_db()

    row = conn.execute(
        """
        SELECT *
        FROM shops
        WHERE id = (
            SELECT shop_id
            FROM users
            WHERE id = ?
        )
        """,
        (user_id,)
    ).fetchone()

    conn.close()

    return row


def get_shop_by_order_reference(order_reference):

    conn = get_db()

    row = conn.execute(
        """
        SELECT s.*
        FROM shops s
        INNER JOIN orders o
            ON o.shop_id = s.id
        WHERE o.order_reference = ?
        LIMIT 1
        """,
        (order_reference,)
    ).fetchone()

    conn.close()

    return row


def get_order_delivery_charge(order_reference, customer=None):

    if customer is None:
        customer = get_user_from_session()

    conn = get_db()

    shops = conn.execute(
        """
        SELECT DISTINCT shop_id
        FROM orders
        WHERE order_reference = ?
        """,
        (order_reference,)
    ).fetchall()

    total_charge = 0.0

    for shop_row in shops:
        shop = conn.execute(
            """
            SELECT *
            FROM shops
            WHERE id = ?
            """,
            (shop_row["shop_id"],)
        ).fetchone()
        if shop:
            total_charge += calculate_delivery_charge(shop, customer)

    conn.close()

    return round(total_charge, 2)


# ============================================================
# CURRENCY
# ============================================================

def format_currency(value):

    return f"₹{float(value):.2f}"


@app.template_filter("currency")
def currency_filter(value):

    return format_currency(value)


# ============================================================
# CART
# ============================================================

def get_cart_items():

    cart = session.get(
        "cart",
        []
    )

    item_details = []

    total = 0

    for entry in cart:

        try:
            product_id = int(
                entry["product_id"]
            )
        except (ValueError, KeyError, TypeError):
            continue

        product = get_product_by_id(
            product_id
        )

        if not product:
            continue

        qty = max(
            1,
            int(entry.get("quantity", 1))
        )

        line_total = (
            float(product["price"]) * qty
        )

        total += line_total

        item_details.append(
            {
                "product": product,
                "quantity": qty,
                "line_total": line_total,
            }
        )

    return item_details, total


# ============================================================
# UPI PAYMENT VALIDATION
# ============================================================

def validate_upi_payment(
    upi_id,
    amount,
    transaction_id
):

    if not upi_id or not transaction_id:

        return (
            False,
            "UPI ID and transaction ID are required."
        )

    if amount <= 0:

        return (
            False,
            "Invalid payment amount."
        )

    gateway_url = os.getenv(
        "UPI_GATEWAY_URL"
    )

    # --------------------------------------------------------
    # REAL GATEWAY MODE
    # --------------------------------------------------------

    if gateway_url:

        try:

            payload = urllib_parse.urlencode(
                {
                    "upi_id": upi_id,
                    "amount": str(amount),
                    "transaction_id": transaction_id,
                }
            ).encode()

            req = urllib_request.Request(
                gateway_url,
                data=payload,
                method="POST"
            )

            with urllib_request.urlopen(
                req,
                timeout=10
            ) as response:

                body = response.read().decode(
                    "utf-8",
                    errors="ignore"
                )

                if (
                    response.status == 200
                    and "success" in body.lower()
                ):

                    return (
                        True,
                        "Payment verified successfully."
                    )

                return (
                    False,
                    "Payment gateway rejected the transaction."
                )

        except Exception:

            return (
                False,
                "Payment gateway verification failed. Please try again."
            )

    # --------------------------------------------------------
    # DEMO MODE
    # --------------------------------------------------------

    if not re.match(
        r"^[A-Z0-9\-_.@]{4,}$",
        str(transaction_id).upper()
    ):

        return (
            False,
            "Invalid transaction reference."
        )

    return (
        True,
        "Demo verification passed. Connect a real payment gateway in .env for live transactions."
    )


# ============================================================
# STOCK REDUCTION
# ============================================================

def reduce_stock_for_order(
    conn,
    product_id,
    quantity
):

    product = conn.execute(
        """
        SELECT *
        FROM products
        WHERE id = ?
        """,
        (product_id,)
    ).fetchone()

    if not product:
        return False

    if product["available_stock"] < quantity:
        return False

    new_available = (
        product["available_stock"] - quantity
    )

    new_sold = (
        product["sold_quantity"] + quantity
    )

    conn.execute(
        """
        UPDATE products

        SET
            available_stock = ?,
            sold_quantity = ?

        WHERE id = ?
        """,
        (
            new_available,
            new_sold,
            product_id
        )
    )

    return True


# ============================================================
# CUSTOMER ORDERS
# ============================================================

def get_customer_orders(customer_id):

    conn = get_db()

    rows = conn.execute(
        """
        SELECT
            o.order_reference,
            o.order_status,
            o.payment_status,
            o.payment_method,
            o.delivery_date,
            o.created_at,
            o.amount,
            o.quantity,
            p.name AS product_name,
            s.shop_name,
            COUNT(*) AS item_count

        FROM orders o

        INNER JOIN products p
            ON p.id = o.product_id

        INNER JOIN shops s
            ON s.id = o.shop_id

        WHERE o.customer_id = ?

        GROUP BY o.order_reference

        ORDER BY o.created_at DESC
        """,
        (customer_id,)
    ).fetchall()

    conn.close()

    return rows


# ============================================================
# ORDER SUMMARY
# ============================================================

def build_order_summary(order_reference):

    conn = get_db()

    rows = conn.execute(
        """
        SELECT
            o.*,

            p.name AS product_name,
            p.image,

            s.shop_name,
            s.owner_name,
            s.mobile AS shop_mobile,
            s.address AS shop_address,
            s.village AS shop_village,
            s.asorpay_upi_id,
            s.asorpay_qr_code,

            p.brand,
            p.manufacturer,
            p.manufacturing_date,
            p.expiry_date,

            c.name AS customer_name,
            c.mobile AS customer_mobile,
            c.address AS customer_address,
            c.village AS customer_village,
            c.pin_code AS customer_pin

        FROM orders o

        INNER JOIN products p
            ON p.id = o.product_id

        INNER JOIN shops s
            ON s.id = o.shop_id

        INNER JOIN users c
            ON c.id = o.customer_id

        WHERE o.order_reference = ?

        ORDER BY o.id ASC
        """,
        (order_reference,)
    ).fetchall()

    conn.close()

    return rows


# ============================================================
# HOME
# ============================================================

@app.route("/")
def index():

    if session.get("user_id"):

        if session.get("user_type") == "customer":
            return redirect(
                url_for("customer_dashboard")
            )

        if session.get("user_type") == "owner":
            return redirect(
                url_for("owner_dashboard")
            )

    return redirect(
        url_for("customer_dashboard")
    )


# ============================================================
# CUSTOMER LOGIN
# ============================================================

@app.route(
    "/customer-login",
    methods=["GET", "POST"]
)
def customer_login():

    if request.method == "POST":

        email = request.form.get(
            "email",
            ""
        ).strip().lower()

        password = request.form.get(
            "password",
            ""
        )

        conn = get_db()

        user = conn.execute(
            """
            SELECT *
            FROM users

            WHERE email = ?
            AND user_type = 'customer'
            """,
            (email,)
        ).fetchone()

        conn.close()

        if user and check_password_hash(
            user["password_hash"],
            password
        ):

            session["user_id"] = user["id"]
            session["user_type"] = "customer"
            session["user_name"] = user["name"]

            flash(
                "Welcome back, customer.",
                "success"
            )

            return redirect(
                url_for("customer_dashboard")
            )

        flash(
            "Invalid customer credentials.",
            "error"
        )

    return render_template(
        "customer_login.html"
    )


# ============================================================
# CUSTOMER REGISTER
# ============================================================

@app.route(
    "/customer-register",
    methods=["GET", "POST"]
)
def customer_register():

    if request.method == "POST":

        name = request.form.get(
            "name",
            ""
        ).strip()

        email = request.form.get(
            "email",
            ""
        ).strip().lower()

        mobile = request.form.get(
            "mobile",
            ""
        ).strip()

        address = request.form.get(
            "address",
            ""
        ).strip()

        village = request.form.get(
            "village",
            ""
        ).strip()

        pin_code = request.form.get(
            "pin_code",
            ""
        ).strip()

        password = request.form.get(
            "password",
            ""
        )

        confirm_password = request.form.get(
            "confirm_password",
            ""
        )

        if not all(
            [
                name,
                email,
                mobile,
                address,
                village,
                pin_code,
                password,
            ]
        ):

            flash(
                "Please fill all customer registration fields.",
                "error"
            )

            return render_template(
                "customer_register.html"
            )

        if password != confirm_password:

            flash(
                "Passwords do not match.",
                "error"
            )

            return render_template(
                "customer_register.html"
            )

        conn = get_db()

        existing = conn.execute(
            """
            SELECT id
            FROM users
            WHERE email = ?
            """,
            (email,)
        ).fetchone()

        if existing:

            conn.close()

            flash(
                "This email is already registered.",
                "error"
            )

            return render_template(
                "customer_register.html"
            )

        try:

            user_id = conn.execute(
                """
                INSERT INTO users (
                    name,
                    email,
                    password_hash,
                    mobile,
                    address,
                    village,
                    pin_code,
                    user_type
                )

                VALUES (?, ?, ?, ?, ?, ?, ?, 'customer')
                """,
                (
                    name,
                    email,
                    generate_password_hash(password),
                    mobile,
                    address,
                    village,
                    pin_code,
                )
            ).lastrowid

            conn.commit()

        except sqlite3.Error as error:

            conn.rollback()
            conn.close()

            flash(
                f"Registration failed: {error}",
                "error"
            )

            return render_template(
                "customer_register.html"
            )

        conn.close()

        session["user_id"] = user_id
        session["user_type"] = "customer"
        session["user_name"] = name

        flash(
            "Customer account created successfully.",
            "success"
        )

        return redirect(
            url_for("customer_dashboard")
        )

    return render_template(
        "customer_register.html"
    )


# ============================================================
# OWNER LOGIN
# ============================================================

@app.route(
    "/owner-login",
    methods=["GET", "POST"]
)
def owner_login():

    if request.method == "POST":

        shop_name = request.form.get(
            "shop_name",
            ""
        ).strip()

        email = request.form.get(
            "email",
            ""
        ).strip().lower()

        password = request.form.get(
            "password",
            ""
        )

        conn = get_db()

        user = conn.execute(
            """
            SELECT *
            FROM users

            WHERE email = ?
            AND user_type = 'owner'
            """,
            (email,)
        ).fetchone()

        if user:

            shop = conn.execute(
                """
                SELECT *
                FROM shops
                WHERE id = ?
                """,
                (user["shop_id"],)
            ).fetchone()

            if (
                shop_name
                and shop
                and shop["shop_name"].strip().lower()
                != shop_name.strip().lower()
            ):

                conn.close()

                flash(
                    "Invalid shop owner credentials.",
                    "error"
                )

                return render_template(
                    "owner_login.html"
                )

        conn.close()

        if user and check_password_hash(
            user["password_hash"],
            password
        ):

            session["user_id"] = user["id"]
            session["user_type"] = "owner"
            session["user_name"] = user["name"]

            flash(
                "Welcome back, shop owner.",
                "success"
            )

            return redirect(
                url_for("owner_dashboard")
            )

        flash(
            "Invalid shop owner credentials.",
            "error"
        )

    return render_template(
        "owner_login.html"
    )


# ============================================================
# OWNER REGISTER
# ============================================================

@app.route(
    "/owner-register",
    methods=["GET", "POST"]
)
def owner_register():

    if request.method == "POST":

        shop_name = request.form.get(
            "shop_name",
            ""
        ).strip()

        owner_name = request.form.get(
            "owner_name",
            ""
        ).strip()

        email = request.form.get(
            "email",
            ""
        ).strip().lower()

        mobile = request.form.get(
            "mobile",
            ""
        ).strip()

        address = request.form.get(
            "address",
            ""
        ).strip()

        village = request.form.get(
            "village",
            ""
        ).strip()

        pin_code = request.form.get(
            "pin_code",
            ""
        ).strip()

        password = request.form.get(
            "password",
            ""
        )

        confirm_password = request.form.get(
            "confirm_password",
            ""
        )

        # ----------------------------------------------------
        # VALIDATION
        # ----------------------------------------------------

        if not all(
            [
                shop_name,
                owner_name,
                email,
                mobile,
                address,
                village,
                pin_code,
                password,
            ]
        ):

            flash(
                "Please complete all shop owner registration fields.",
                "error"
            )

            return render_template(
                "owner_register.html"
            )

        if password != confirm_password:

            flash(
                "Passwords do not match.",
                "error"
            )

            return render_template(
                "owner_register.html"
            )

        conn = get_db()

        try:

            # ------------------------------------------------
            # CHECK EXISTING SHOP
            # ------------------------------------------------

            existing_shop = conn.execute(
                """
                SELECT id
                FROM shops

                WHERE email = ?
                OR LOWER(shop_name) = LOWER(?)
                """,
                (
                    email,
                    shop_name,
                )
            ).fetchone()

            if existing_shop:

                conn.close()

                flash(
                    "A shop with that email or name already exists.",
                    "error"
                )

                return render_template(
                    "owner_register.html"
                )

            # ------------------------------------------------
            # CHECK EXISTING USER EMAIL
            # ------------------------------------------------

            existing_user = conn.execute(
                """
                SELECT id
                FROM users
                WHERE email = ?
                """,
                (email,)
            ).fetchone()

            if existing_user:

                conn.close()

                flash(
                    "This email is already registered.",
                    "error"
                )

                return render_template(
                    "owner_register.html"
                )

            # ------------------------------------------------
            # CREATE SHOP
            # ------------------------------------------------

            shop_id = conn.execute(
                """
                INSERT INTO shops (
                    shop_name,
                    owner_name,
                    email,
                    mobile,
                    address,
                    village,
                    pin_code,
                    delivery_radius,
                    delivery_charge,
                    delivery_time
                )

                VALUES (
                    ?,
                    ?,
                    ?,
                    ?,
                    ?,
                    ?,
                    ?,
                    8,
                    20,
                    'Today, 5:00 PM - 7:00 PM'
                )
                """,
                (
                    shop_name,
                    owner_name,
                    email,
                    mobile,
                    address,
                    village,
                    pin_code,
                )
            ).lastrowid

            # ------------------------------------------------
            # CREATE OWNER USER
            # ------------------------------------------------

            user_id = conn.execute(
                """
                INSERT INTO users (
                    name,
                    email,
                    password_hash,
                    mobile,
                    address,
                    village,
                    pin_code,
                    user_type,
                    shop_id
                )

                VALUES (
                    ?,
                    ?,
                    ?,
                    ?,
                    ?,
                    ?,
                    ?,
                    'owner',
                    ?
                )
                """,
                (
                    owner_name,
                    email,
                    generate_password_hash(password),
                    mobile,
                    address,
                    village,
                    pin_code,
                    shop_id,
                )
            ).lastrowid

            # ------------------------------------------------
            # COMMIT BOTH TOGETHER
            # ------------------------------------------------

            conn.commit()

        except sqlite3.OperationalError as error:

            conn.rollback()
            conn.close()

            flash(
                f"Database error: {error}",
                "error"
            )

            return render_template(
                "owner_register.html"
            )

        except sqlite3.IntegrityError as error:

            conn.rollback()
            conn.close()

            flash(
                f"Registration error: {error}",
                "error"
            )

            return render_template(
                "owner_register.html"
            )

        except Exception as error:

            conn.rollback()
            conn.close()

            flash(
                f"Registration failed: {error}",
                "error"
            )

            return render_template(
                "owner_register.html"
            )

        conn.close()

        # ----------------------------------------------------
        # LOGIN AUTOMATICALLY
        # ----------------------------------------------------

        session["user_id"] = user_id
        session["user_type"] = "owner"
        session["user_name"] = owner_name

        flash(
            "Shop owner account created successfully.",
            "success"
        )

        return redirect(
            url_for("owner_dashboard")
        )

    return render_template(
        "owner_register.html"
    )


# ============================================================
# LOGOUT
# ============================================================

@app.route("/logout")
def logout():

    session.clear()

    flash(
        "You have been logged out.",
        "success"
    )

    return redirect(
        url_for("index")
    )


# ============================================================
# CUSTOMER DASHBOARD
# ============================================================

@app.route("/customer-dashboard")
def customer_dashboard():

    query = request.args.get(
        "q",
        ""
    ).strip()

    category = request.args.get(
        "category",
        ""
    ).strip()

    brand = request.args.get(
        "brand",
        ""
    ).strip()

    shop = request.args.get(
        "shop",
        ""
    ).strip()

    conn = get_db()

    sql = """
        SELECT
            p.*,
            s.shop_name,
            s.delivery_radius,
            s.village AS shop_village

        FROM products p

        INNER JOIN shops s
            ON s.id = p.shop_id

        WHERE p.available_stock > 0

        AND (
            p.expiry_date IS NULL
            OR date(p.expiry_date) >= date('now')
        )
    """

    params = []

    if query:

        sql += """
            AND (
                LOWER(p.name) LIKE LOWER(?)
                OR LOWER(p.category) LIKE LOWER(?)
                OR LOWER(p.brand) LIKE LOWER(?)
                OR LOWER(p.manufacturer) LIKE LOWER(?)
                OR LOWER(s.shop_name) LIKE LOWER(?)
            )
        """

        like_value = f"%{query}%"

        params.extend(
            [
                like_value,
                like_value,
                like_value,
                like_value,
                like_value,
            ]
        )

    if category:

        sql += """
            AND LOWER(p.category) = LOWER(?)
        """

        params.append(category)

    if brand:

        sql += """
            AND LOWER(p.brand) = LOWER(?)
        """

        params.append(brand)

    if shop:

        sql += """
            AND LOWER(s.shop_name) = LOWER(?)
        """

        params.append(shop)

    sql += """
        ORDER BY
            p.available_stock DESC,
            p.price ASC
    """

    products = conn.execute(
        sql,
        params
    ).fetchall()

    conn.close()

    return render_template(
        "customer_dashboard.html",
        products=products,
        q=query,
        category=category,
        brand=brand,
        shop=shop
    )


# ============================================================
# PRODUCT DETAILS
# ============================================================

@app.route(
    "/product/<int:product_id>"
)
def product_details(product_id):

    product = get_product_by_id(
        product_id
    )

    if not product:

        flash(
            "Product not found.",
            "error"
        )

        return redirect(
            url_for("customer_dashboard")
        )

    if not product_is_available(product):

        flash(
            "This product is no longer available for purchase.",
            "error"
        )

        return redirect(
            url_for("customer_dashboard")
        )

    return render_template(
        "product_details.html",
        product=product
    )


# ============================================================
# CART PAGE
# ============================================================

@app.route("/cart")
def cart_page():

    items, total = get_cart_items()

    return render_template(
        "cart.html",
        items=items,
        total=total
    )


# ============================================================
# ADD TO CART
# ============================================================

@app.route(
    "/cart/add",
    methods=["POST"]
)
def add_to_cart():

    try:

        product_id = int(
            request.form.get(
                "product_id"
            )
        )

        quantity = max(
            1,
            int(
                request.form.get(
                    "quantity",
                    1
                )
            )
        )

    except (ValueError, TypeError):

        flash(
            "Invalid product or quantity.",
            "error"
        )

        return redirect(
            url_for("customer_dashboard")
        )

    product = get_product_by_id(
        product_id
    )

    if not product:

        flash(
            "Product not found.",
            "error"
        )

        return redirect(
            url_for("customer_dashboard")
        )

    if not product_is_available(product):

        flash(
            "This product is not available right now.",
            "error"
        )

        return redirect(
            url_for("customer_dashboard")
        )

    cart = session.get(
        "cart",
        []
    )

    existing = False

    for item in cart:

        if int(item["product_id"]) == product_id:

            new_quantity = (
                int(item.get("quantity", 1))
                + quantity
            )

            if new_quantity > product["available_stock"]:

                new_quantity = product[
                    "available_stock"
                ]

                flash(
                    f"Only {product['available_stock']} units are available.",
                    "error"
                )

            item["quantity"] = new_quantity

            existing = True

            break

    if not existing:

        cart.append(
            {
                "product_id": product_id,
                "quantity": min(
                    quantity,
                    product["available_stock"]
                )
            }
        )

    session["cart"] = cart

    flash(
        "Product added to cart.",
        "success"
    )

    return redirect(
        url_for("cart_page")
    )


# ============================================================
# UPDATE CART
# ============================================================

@app.route(
    "/cart/update/<int:product_id>",
    methods=["POST"]
)
def update_cart(product_id):

    if not ensure_logged_in("customer"):
        return redirect(
            url_for("customer_login")
        )

    try:

        quantity = max(
            1,
            int(
                request.form.get(
                    "quantity",
                    1
                )
            )
        )

    except (ValueError, TypeError):

        quantity = 1

    product = get_product_by_id(
        product_id
    )

    if not product:

        flash(
            "Product not found.",
            "error"
        )

        return redirect(
            url_for("cart_page")
        )

    quantity = min(
        quantity,
        product["available_stock"]
    )

    cart = session.get(
        "cart",
        []
    )

    for item in cart:

        if int(item["product_id"]) == product_id:

            item["quantity"] = quantity

            break

    session["cart"] = cart

    flash(
        "Cart updated.",
        "success"
    )

    return redirect(
        url_for("cart_page")
    )


# ============================================================
# REMOVE FROM CART
# ============================================================

@app.route(
    "/cart/remove/<int:product_id>",
    methods=["POST"]
)
def remove_from_cart(product_id):

    if not ensure_logged_in("customer"):
        return redirect(
            url_for("customer_login")
        )

    cart = session.get(
        "cart",
        []
    )

    session["cart"] = [
        item
        for item in cart
        if int(item["product_id"]) != product_id
    ]

    flash(
        "Product removed from cart.",
        "success"
    )

    return redirect(
        url_for("cart_page")
    )


# ============================================================
# CHECKOUT
# ============================================================

@app.route(
    "/checkout",
    methods=["GET", "POST"]
)
def checkout_page():

    if not ensure_logged_in("customer"):
        return redirect(
            url_for("customer_login")
        )

    customer = get_user_from_session()

    items, total = get_cart_items()

    delivery_charge = 0.0
    seen_shops = set()
    conn = get_db()

    try:
        for item in items:
            shop_id = item["product"]["shop_id"]
            if shop_id in seen_shops:
                continue
            seen_shops.add(shop_id)
            shop = conn.execute(
                """
                SELECT *
                FROM shops
                WHERE id = ?
                """,
                (shop_id,)
            ).fetchone()
            if shop:
                delivery_charge += calculate_delivery_charge(shop, customer)
    finally:
        conn.close()

    if not items:

        flash(
            "Your cart is empty.",
            "error"
        )

        return redirect(
            url_for("customer_dashboard")
        )

    if request.method == "POST":

        order_reference = (
            f"LM-{uuid.uuid4().hex[:8].upper()}"
        )

        delivery_address = request.form.get(
            "delivery_address",
            customer["address"]
        )

        village = request.form.get(
            "village",
            customer["village"]
        )

        pin_code = request.form.get(
            "pin_code",
            customer["pin_code"]
        )

        order_date = (
            datetime.now()
            .date()
            .isoformat()
        )

        conn = get_db()

        try:

            for item in items:

                product = get_product_by_id(
                    item["product"]["id"]
                )

                if (
                    not product
                    or product["available_stock"]
                    < item["quantity"]
                ):

                    conn.rollback()
                    conn.close()

                    flash(
                        f"Stock for {item['product']['name']} is not enough.",
                        "error"
                    )

                    return redirect(
                        url_for("cart_page")
                    )

            for item in items:

                product = item["product"]
                quantity = item["quantity"]

                shop = conn.execute(
                    """
                    SELECT *
                    FROM shops
                    WHERE id = ?
                    """,
                    (product["shop_id"],)
                ).fetchone()

                amount = (
                    float(product["price"])
                    * quantity
                )

                conn.execute(
                    """
                    INSERT INTO orders (
                        order_reference,
                        customer_id,
                        shop_id,
                        product_id,
                        quantity,
                        amount,
                        delivery_address,
                        village,
                        pin_code,
                        order_date,
                        order_status,
                        payment_method,
                        payment_status,
                        created_at
                    )

                    VALUES (
                        ?,
                        ?,
                        ?,
                        ?,
                        ?,
                        ?,
                        ?,
                        ?,
                        ?,
                        ?,
                        'Order Placed',
                        'COD',
                        'Pending',
                        datetime('now')
                    )
                    """,
                    (
                        order_reference,
                        customer["id"],
                        product["shop_id"],
                        product["id"],
                        quantity,
                        amount,
                        delivery_address,
                        village,
                        pin_code,
                        order_date,
                    )
                )

                conn.execute(
                    """
                    INSERT INTO payments (
                        order_reference,
                        payment_method,
                        amount,
                        payment_status
                    )

                    VALUES (
                        ?,
                        'COD',
                        ?,
                        'Pending'
                    )
                    """,
                    (
                        order_reference,
                        amount
                    )
                )

            conn.commit()

        except Exception as error:

            conn.rollback()
            conn.close()

            flash(
                f"Could not create order: {error}",
                "error"
            )

            return redirect(
                url_for("cart_page")
            )

        conn.close()

        session["cart"] = []

        return redirect(
            url_for(
                "payment_page",
                order_reference=order_reference
            )
        )

    return render_template(
        "checkout.html",
        items=items,
        total=total,
        delivery_charge=delivery_charge,
        total_with_delivery=total + delivery_charge,
        customer=customer
    )


# ============================================================
# PAYMENT PAGE
# ============================================================

@app.route(
    "/payment/<order_reference>"
)
def payment_page(order_reference):

    if not ensure_logged_in("customer"):
        return redirect(
            url_for("customer_login")
        )

    rows = build_order_summary(
        order_reference
    )

    if not rows:

        flash(
            "Order not found.",
            "error"
        )

        return redirect(
            url_for("customer_dashboard")
        )

    total_amount = sum(
        float(row["amount"])
        for row in rows
    ) + get_order_delivery_charge(
        order_reference,
        get_user_from_session()
    )

    customer = get_user_from_session()

    return render_template(
        "payment.html",
        rows=rows,
        total_amount=total_amount,
        customer=customer,
        order_reference=order_reference
    )


# ============================================================
# PROCESS PAYMENT
# ============================================================

@app.route(
    "/payment/<order_reference>/process",
    methods=["POST"]
)
def process_payment(order_reference):

    if not ensure_logged_in("customer"):
        return redirect(
            url_for("customer_login")
        )

    payment_method = request.form.get(
        "payment_method",
        "ASORPAY"
    ).upper()

    rows = build_order_summary(
        order_reference
    )

    if not rows:

        flash(
            "Order not found.",
            "error"
        )

        return redirect(
            url_for("customer_dashboard")
        )

    delivery_charge = get_order_delivery_charge(
        order_reference,
        get_user_from_session()
    )

    total = sum(
        float(item["amount"])
        for item in rows
    ) + delivery_charge

    conn = get_db()

    try:

        # ----------------------------------------------------
        # UPI / ASORPAY
        # ----------------------------------------------------

        if payment_method in ("UPI", "ASORPAY"):

            upi_id = request.form.get(
                "upi_id",
                ""
            ).strip()

            if payment_method == "ASORPAY" and not upi_id:
                upi_id = request.form.get(
                    "asorpay_upi_id",
                    ""
                ).strip()

            transaction_id = (
                request.form.get(
                    "transaction_id",
                    ""
                ).strip()
                or
                f"UPI-{uuid.uuid4().hex[:10].upper()}"
            )

            ok, message = validate_upi_payment(
                upi_id,
                total,
                transaction_id
            )

            if not ok:

                conn.close()

                flash(
                    message,
                    "error"
                )

                return redirect(
                    url_for(
                        "payment_page",
                        order_reference=order_reference
                    )
                )

            # Check stock
            for item in rows:

                product = conn.execute(
                    """
                    SELECT *
                    FROM products
                    WHERE id = ?
                    """,
                    (item["product_id"],)
                ).fetchone()

                if (
                    not product
                    or product["available_stock"]
                    < item["quantity"]
                ):

                    conn.rollback()
                    conn.close()

                    flash(
                        f"Stock for {item['product_name']} is not enough for this order.",
                        "error"
                    )

                    return redirect(
                        url_for("cart_page")
                    )

            # Reduce stock using SAME connection
            for item in rows:

                success = reduce_stock_for_order(
                    conn,
                    item["product_id"],
                    item["quantity"]
                )

                if not success:

                    conn.rollback()
                    conn.close()

                    flash(
                        f"Could not update stock for {item['product_name']}.",
                        "error"
                    )

                    return redirect(
                        url_for("customer_dashboard")
                    )

                conn.execute(
                    """
                    UPDATE orders

                    SET
                        payment_method = 'ASORPAY',
                        payment_status = 'Paid',
                        order_status = 'Seller Confirmed'

                    WHERE order_reference = ?
                    AND product_id = ?
                    """,
                    (
                        order_reference,
                        item["product_id"]
                    )
                )

            conn.execute(
                """
                INSERT INTO payments (
                    order_reference,
                    payment_method,
                    transaction_id,
                    amount,
                    payment_status,
                    payment_date
                )

                VALUES (
                    ?,
                    'ASORPAY',
                    ?,
                    ?,
                    'Paid',
                    datetime('now')
                )
                """,
                (
                    order_reference,
                    transaction_id,
                    total
                )
            )

            conn.commit()
            conn.close()

            customer = get_user_from_session()
            shop = get_shop_by_order_reference(order_reference)
            send_order_notifications(
                order_reference,
                customer,
                shop,
                rows,
            )

            flash(
                "AsorPay payment successful.",
                "success"
            )

            return redirect(
                url_for("order_success", order_reference=order_reference)
            )

        # ----------------------------------------------------
        # COD
        # ----------------------------------------------------

        if payment_method == "COD":

            # Check stock
            for item in rows:

                product = conn.execute(
                    """
                    SELECT *
                    FROM products
                    WHERE id = ?
                    """,
                    (item["product_id"],)
                ).fetchone()

                if (
                    not product
                    or product["available_stock"]
                    < item["quantity"]
                ):

                    conn.rollback()
                    conn.close()

                    flash(
                        f"Stock for {item['product_name']} is not enough for this order.",
                        "error"
                    )

                    return redirect(
                        url_for("cart_page")
                    )

            # Reduce stock using SAME connection
            for item in rows:

                success = reduce_stock_for_order(
                    conn,
                    item["product_id"],
                    item["quantity"]
                )

                if not success:

                    conn.rollback()
                    conn.close()

                    flash(
                        f"Could not update stock for {item['product_name']}.",
                        "error"
                    )

                    return redirect(
                        url_for("customer_dashboard")
                    )

                conn.execute(
                    """
                    UPDATE orders

                    SET
                        payment_method = 'COD',
                        payment_status = 'Cash on Delivery',
                        order_status = 'Seller Confirmed'

                    WHERE order_reference = ?
                    AND product_id = ?
                    """,
                    (
                        order_reference,
                        item["product_id"]
                    )
                )

            conn.execute(
                """
                INSERT INTO payments (
                    order_reference,
                    payment_method,
                    amount,
                    payment_status,
                    payment_date
                )

                VALUES (
                    ?,
                    'COD',
                    ?,
                    'Cash on Delivery',
                    datetime('now')
                )
                """,
                (
                    order_reference,
                    total
                )
            )

            conn.commit()
            conn.close()

            customer = get_user_from_session()
            shop = get_shop_by_order_reference(order_reference)
            send_order_notifications(
                order_reference,
                customer,
                shop,
                rows,
            )

            flash(
                "Cash on Delivery order placed successfully.",
                "success"
            )

            return redirect(
                url_for("order_success", order_reference=order_reference)
            )

        conn.close()

        flash(
            "Invalid payment method.",
            "error"
        )

        return redirect(
            url_for(
                "payment_page",
                order_reference=order_reference
            )
        )

    except sqlite3.Error as error:

        conn.rollback()
        conn.close()

        flash(
            f"Payment database error: {error}",
            "error"
        )

        return redirect(
            url_for(
                "payment_page",
                order_reference=order_reference
            )
        )

    except Exception as error:

        conn.rollback()
        conn.close()

        flash(
            f"Payment processing failed: {error}",
            "error"
        )

        return redirect(
            url_for(
                "payment_page",
                order_reference=order_reference
            )
        )


# ============================================================
# ORDER SUCCESS PAGE
# ============================================================

@app.route("/order-success/<order_reference>")
def order_success(order_reference):

    if not ensure_logged_in("customer"):
        return redirect(
            url_for("customer_login")
        )

    rows = build_order_summary(
        order_reference
    )

    if not rows:
        flash(
            "Order not found.",
            "error"
        )
        return redirect(
            url_for("customer_dashboard")
        )

    total = sum(
        float(row["amount"])
        for row in rows
    ) + get_order_delivery_charge(
        order_reference,
        get_user_from_session()
    )

    return render_template(
        "order_success.html",
        rows=rows,
        total=total,
        order_reference=order_reference
    )


# ============================================================
# CUSTOMER ORDERS PAGE
# ============================================================

@app.route("/orders")
def customer_orders():

    if not ensure_logged_in("customer"):
        return redirect(
            url_for("customer_login")
        )

    orders = get_customer_orders(
        session["user_id"]
    )

    return render_template(
        "orders.html",
        orders=orders
    )


# ============================================================
# OWNER PROFILE
# ============================================================

@app.route(
    "/owner-profile",
    methods=["GET", "POST"]
)
def owner_profile():

    if not ensure_logged_in("owner"):
        return redirect(
            url_for("owner_login")
        )

    shop = get_shop_by_user(
        session["user_id"]
    )

    if not shop:
        flash(
            "Shop profile not found.",
            "error"
        )
        return redirect(
            url_for("owner_dashboard")
        )

    if request.method == "POST":

        shop_name = request.form.get(
            "shop_name",
            shop["shop_name"]
        ).strip()
        owner_name = request.form.get(
            "owner_name",
            shop["owner_name"]
        ).strip()
        mobile = request.form.get(
            "mobile",
            shop["mobile"] or ""
        ).strip()
        address = request.form.get(
            "address",
            shop["address"] or ""
        ).strip()
        village = request.form.get(
            "village",
            shop["village"] or ""
        ).strip()
        pin_code = request.form.get(
            "pin_code",
            shop["pin_code"] or ""
        ).strip()
        delivery_radius = int(
            request.form.get(
                "delivery_radius",
                shop["delivery_radius"] or 5
            )
        )
        delivery_charge = float(
            request.form.get(
                "delivery_charge",
                shop["delivery_charge"] or 20
            )
        )
        delivery_time = request.form.get(
            "delivery_time",
            shop["delivery_time"] or "Today, 5:00 PM - 7:00 PM"
        ).strip()
        available_delivery_areas = request.form.get(
            "available_delivery_areas",
            shop["available_delivery_areas"] or "Village and nearby town"
        ).strip()
        asorpay_upi_id = request.form.get(
            "asorpay_upi_id",
            shop["asorpay_upi_id"] or ""
        ).strip()

        qr_path = shop["asorpay_qr_code"] or ""

        uploaded_qr = request.files.get("asorpay_qr_code_file")
        if uploaded_qr and uploaded_qr.filename:
            filename = secure_filename(uploaded_qr.filename)
            ext = os.path.splitext(filename)[1].lower()
            if ext in [".jpg", ".jpeg", ".png", ".webp"]:
                unique_name = f"{uuid.uuid4().hex}{ext}"
                uploaded_qr.save(
                    os.path.join(
                        app.config["UPLOAD_FOLDER"],
                        unique_name,
                    )
                )
                qr_path = f"uploads/{unique_name}"
            else:
                flash(
                    "QR code must be a JPG, PNG, or WEBP image.",
                    "error"
                )
                return redirect(
                    url_for("owner_profile")
                )

        conn = get_db()
        conn.execute(
            """
            UPDATE shops
            SET
                shop_name = ?,
                owner_name = ?,
                mobile = ?,
                address = ?,
                village = ?,
                pin_code = ?,
                delivery_radius = ?,
                delivery_charge = ?,
                delivery_time = ?,
                available_delivery_areas = ?,
                asorpay_upi_id = ?,
                asorpay_qr_code = ?
            WHERE id = ?
            """,
            (
                shop_name,
                owner_name,
                mobile,
                address,
                village,
                pin_code,
                delivery_radius,
                delivery_charge,
                delivery_time,
                available_delivery_areas,
                asorpay_upi_id,
                qr_path,
                shop["id"],
            )
        )
        conn.commit()
        conn.close()

        flash(
            "Shop profile updated successfully.",
            "success"
        )
        return redirect(
            url_for("owner_dashboard")
        )

    return render_template(
        "owner_profile.html",
        shop=shop
    )


# ============================================================
# CUSTOMER PROFILE
# ============================================================

@app.route("/profile")
def customer_profile():

    if not ensure_logged_in("customer"):
        return redirect(
            url_for("customer_login")
        )

    user = get_user_from_session()

    return render_template(
        "profile.html",
        user=user
    )


# ============================================================
# OWNER DASHBOARD
# ============================================================

@app.route("/owner-dashboard")
def owner_dashboard():

    if not ensure_logged_in("owner"):
        return redirect(
            url_for("owner_login")
        )

    shop = get_shop_by_user(
        session["user_id"]
    )

    if not shop:

        flash(
            "No shop profile found for this owner.",
            "error"
        )

        return redirect(
            url_for("logout")
        )

    conn = get_db()

    total_products = conn.execute(
        """
        SELECT COUNT(*)
        FROM products
        WHERE shop_id = ?
        """,
        (shop["id"],)
    ).fetchone()[0]

    available_stock = conn.execute(
        """
        SELECT COALESCE(
            SUM(available_stock),
            0
        )

        FROM products

        WHERE shop_id = ?
        """,
        (shop["id"],)
    ).fetchone()[0]

    products_sold = conn.execute(
        """
        SELECT COALESCE(
            SUM(sold_quantity),
            0
        )

        FROM products

        WHERE shop_id = ?
        """,
        (shop["id"],)
    ).fetchone()[0]

    pending_orders = conn.execute(
        """
        SELECT COUNT(*)
        FROM orders

        WHERE shop_id = ?
        AND order_status != 'Delivered'
        """,
        (shop["id"],)
    ).fetchone()[0]

    today_sales = conn.execute(
        """
        SELECT COALESCE(
            SUM(amount),
            0
        )

        FROM orders

        WHERE shop_id = ?

        AND date(created_at)
            = date('now')
        """,
        (shop["id"],)
    ).fetchone()[0]

    products = conn.execute(
        """
        SELECT *
        FROM products

        WHERE shop_id = ?

        ORDER BY created_at DESC
        """,
        (shop["id"],)
    ).fetchall()

    conn.close()

    return render_template(
        "owner_dashboard.html",
        shop=shop,
        total_products=total_products,
        available_stock=available_stock,
        products_sold=products_sold,
        pending_orders=pending_orders,
        today_sales=today_sales,
        products=products
    )


# ============================================================
# OWNER STOCK
# ============================================================

@app.route("/owner-products")
def owner_stock():

    if not ensure_logged_in("owner"):
        return redirect(
            url_for("owner_login")
        )

    shop = get_shop_by_user(
        session["user_id"]
    )

    if not shop:

        flash(
            "Shop not found.",
            "error"
        )

        return redirect(
            url_for("owner_dashboard")
        )

    conn = get_db()

    products = conn.execute(
        """
        SELECT *
        FROM products

        WHERE shop_id = ?

        ORDER BY created_at DESC
        """,
        (shop["id"],)
    ).fetchall()

    conn.close()

    return render_template(
        "stock.html",
        products=products,
        shop=shop
    )


# ============================================================
# DELETE PRODUCT
# ============================================================

@app.route(
    "/owner-products/<int:product_id>/delete",
    methods=["POST"]
)
def delete_product(product_id):

    if not ensure_logged_in("owner"):
        return redirect(
            url_for("owner_login")
        )

    shop = get_shop_by_user(
        session["user_id"]
    )

    conn = get_db()

    try:

        conn.execute(
            """
            DELETE FROM products

            WHERE id = ?
            AND shop_id = ?
            """,
            (
                product_id,
                shop["id"]
            )
        )

        conn.commit()

    except sqlite3.Error as error:

        conn.rollback()

        flash(
            f"Could not delete product: {error}",
            "error"
        )

    else:

        flash(
            "Product deleted successfully.",
            "success"
        )

    conn.close()

    return redirect(
        url_for("owner_stock")
    )


# ============================================================
# EDIT PRODUCT
# ============================================================

@app.route(
    "/owner-products/<int:product_id>/edit",
    methods=["GET", "POST"]
)
def edit_product(product_id):

    if not ensure_logged_in("owner"):
        return redirect(
            url_for("owner_login")
        )

    shop = get_shop_by_user(
        session["user_id"]
    )

    conn = get_db()

    product = conn.execute(
        """
        SELECT *
        FROM products

        WHERE id = ?
        AND shop_id = ?
        """,
        (
            product_id,
            shop["id"]
        )
    ).fetchone()

    conn.close()

    if not product:

        flash(
            "Product not found.",
            "error"
        )

        return redirect(
            url_for("owner_stock")
        )

    if request.method == "POST":

        try:

            name = request.form.get(
                "name",
                ""
            ).strip()

            category = request.form.get(
                "category",
                ""
            ).strip()

            brand = request.form.get(
                "brand",
                ""
            ).strip()

            manufacturer = request.form.get(
                "manufacturer",
                ""
            ).strip()

            description = request.form.get(
                "description",
                ""
            ).strip()

            price = float(
                request.form.get(
                    "price",
                    0
                )
            )

            original_stock = int(
                request.form.get(
                    "original_stock",
                    0
                )
            )

            available_stock = int(
                request.form.get(
                    "available_stock",
                    original_stock
                )
            )

            manufacturing_date = request.form.get(
                "manufacturing_date",
                ""
            )

            expiry_date = request.form.get(
                "expiry_date",
                ""
            )

            delivery_info = (
                request.form.get(
                    "delivery_info",
                    ""
                ).strip()
                or
                "Today, 5:00 PM - 7:00 PM"
            )

            delivery_charge = float(
                request.form.get(
                    "delivery_charge",
                    20
                )
            )

            low_stock_threshold = int(
                request.form.get(
                    "low_stock_threshold",
                    5
                )
            )

            file = request.files.get(
                "image"
            )

            image_path = product["image"]

            if file and file.filename:

                filename = secure_filename(
                    file.filename
                )

                ext = os.path.splitext(
                    filename
                )[1].lower()

                if ext in [
                    ".jpg",
                    ".jpeg",
                    ".png",
                    ".webp"
                ]:

                    unique_name = (
                        f"{uuid.uuid4().hex}{ext}"
                    )

                    file.save(
                        os.path.join(
                            app.config[
                                "UPLOAD_FOLDER"
                            ],
                            unique_name
                        )
                    )

                    image_path = (
                        f"uploads/{unique_name}"
                    )

            conn = get_db()

            conn.execute(
                """
                UPDATE products

                SET
                    name = ?,
                    category = ?,
                    brand = ?,
                    manufacturer = ?,
                    description = ?,
                    image = ?,
                    price = ?,
                    original_stock = ?,
                    available_stock = ?,
                    manufacturing_date = ?,
                    expiry_date = ?,
                    delivery_info = ?,
                    delivery_charge = ?,
                    low_stock_threshold = ?

                WHERE id = ?
                AND shop_id = ?
                """,
                (
                    name,
                    category,
                    brand,
                    manufacturer,
                    description,
                    image_path,
                    price,
                    original_stock,
                    available_stock,
                    manufacturing_date,
                    expiry_date,
                    delivery_info,
                    delivery_charge,
                    low_stock_threshold,
                    product_id,
                    shop["id"]
                )
            )

            conn.commit()
            conn.close()

            flash(
                "Product updated successfully.",
                "success"
            )

            return redirect(
                url_for("owner_stock")
            )

        except Exception as error:

            try:
                conn.rollback()
                conn.close()
            except Exception:
                pass

            flash(
                f"Could not update product: {error}",
                "error"
            )

    return render_template(
        "add_product.html",
        shop=shop,
        product=product,
        edit_mode=True
    )


# ============================================================
# ADD PRODUCT
# ============================================================

@app.route(
    "/owner-products/new",
    methods=["GET", "POST"]
)
def add_product():

    if not ensure_logged_in("owner"):
        return redirect(
            url_for("owner_login")
        )

    shop = get_shop_by_user(
        session["user_id"]
    )

    if not shop:

        flash(
            "Shop not found.",
            "error"
        )

        return redirect(
            url_for("owner_login")
        )

    if request.method == "POST":

        try:

            name = request.form.get(
                "name",
                ""
            ).strip()

            category = request.form.get(
                "category",
                ""
            ).strip()

            brand = request.form.get(
                "brand",
                ""
            ).strip()

            manufacturer = request.form.get(
                "manufacturer",
                ""
            ).strip()

            description = request.form.get(
                "description",
                ""
            ).strip()

            price = float(
                request.form.get(
                    "price",
                    0
                )
            )

            original_stock = int(
                request.form.get(
                    "original_stock",
                    0
                )
            )

            manufacturing_date = request.form.get(
                "manufacturing_date",
                ""
            )

            expiry_date = request.form.get(
                "expiry_date",
                ""
            )

            delivery_info = (
                request.form.get(
                    "delivery_info",
                    ""
                ).strip()
                or
                "Today, 5:00 PM - 7:00 PM"
            )

            delivery_charge = float(
                request.form.get(
                    "delivery_charge",
                    20
                )
            )

            low_stock_threshold = int(
                request.form.get(
                    "low_stock_threshold",
                    5
                )
            )

            file = request.files.get(
                "image"
            )

            if not all(
                [
                    name,
                    category,
                    brand,
                    manufacturer,
                    description,
                    price > 0,
                    original_stock > 0,
                    manufacturing_date,
                    expiry_date,
                ]
            ):

                flash(
                    "Please fill all required product details.",
                    "error"
                )

                return render_template(
                    "add_product.html",
                    shop=shop
                )

            image_path = (
                "uploads/default-product.svg"
            )

            if file and file.filename:

                filename = secure_filename(
                    file.filename
                )

                ext = os.path.splitext(
                    filename
                )[1].lower()

                if ext in [
                    ".jpg",
                    ".jpeg",
                    ".png",
                    ".webp"
                ]:

                    unique_name = (
                        f"{uuid.uuid4().hex}{ext}"
                    )

                    file.save(
                        os.path.join(
                            app.config[
                                "UPLOAD_FOLDER"
                            ],
                            unique_name
                        )
                    )

                    image_path = (
                        f"uploads/{unique_name}"
                    )

            conn = get_db()

            conn.execute(
                """
                INSERT INTO products (
                    shop_id,
                    name,
                    category,
                    brand,
                    manufacturer,
                    description,
                    image,
                    price,
                    original_stock,
                    available_stock,
                    sold_quantity,
                    manufacturing_date,
                    expiry_date,
                    delivery_info,
                    delivery_charge,
                    low_stock_threshold,
                    created_at
                )

                VALUES (
                    ?,
                    ?,
                    ?,
                    ?,
                    ?,
                    ?,
                    ?,
                    ?,
                    ?,
                    ?,
                    0,
                    ?,
                    ?,
                    ?,
                    ?,
                    ?,
                    datetime('now')
                )
                """,
                (
                    shop["id"],
                    name,
                    category,
                    brand,
                    manufacturer,
                    description,
                    image_path,
                    price,
                    original_stock,
                    original_stock,
                    manufacturing_date,
                    expiry_date,
                    delivery_info,
                    delivery_charge,
                    low_stock_threshold,
                )
            )

            conn.commit()
            conn.close()

            flash(
                "Product saved successfully and is now visible to customers.",
                "success"
            )

            return redirect(
                url_for("owner_stock")
            )

        except Exception as error:

            try:
                conn.rollback()
                conn.close()
            except Exception:
                pass

            flash(
                f"Could not save product: {error}",
                "error"
            )

    return render_template(
        "add_product.html",
        shop=shop
    )


# ============================================================
# OWNER ORDERS
# ============================================================

@app.route("/owner-orders")
def owner_orders():

    if not ensure_logged_in("owner"):
        return redirect(
            url_for("owner_login")
        )

    shop = get_shop_by_user(
        session["user_id"]
    )

    conn = get_db()

    orders = conn.execute(
        """
        SELECT
            o.*,
            u.name AS customer_name,
            u.mobile AS customer_mobile,
            p.name AS product_name,
            p.image AS product_image,
            s.shop_name

        FROM orders o

        INNER JOIN users u
            ON u.id = o.customer_id

        INNER JOIN products p
            ON p.id = o.product_id

        INNER JOIN shops s
            ON s.id = o.shop_id

        WHERE o.shop_id = ?

        ORDER BY o.created_at DESC
        """,
        (shop["id"],)
    ).fetchall()

    conn.close()

    return render_template(
        "owner_orders.html",
        orders=orders,
        shop=shop
    )


# ============================================================
# UPDATE OWNER ORDER STATUS
# ============================================================

@app.route(
    "/owner-orders/<order_reference>/status",
    methods=["POST"]
)
def update_owner_order_status(
    order_reference
):

    if not ensure_logged_in("owner"):
        return redirect(
            url_for("owner_login")
        )

    new_status = request.form.get(
        "order_status",
        "Order Placed"
    )

    allowed_statuses = [
        "Order Placed",
        "Seller Confirmed",
        "Preparing",
        "Out for Delivery",
        "Delivered",
        "Cancelled",
    ]

    if new_status not in allowed_statuses:

        flash(
            "Invalid order status.",
            "error"
        )

        return redirect(
            url_for("owner_orders")
        )

    shop = get_shop_by_user(
        session["user_id"]
    )

    conn = get_db()

    conn.execute(
        """
        UPDATE orders

        SET order_status = ?

        WHERE shop_id = ?
        AND order_reference = ?
        """,
        (
            new_status,
            shop["id"],
            order_reference
        )
    )

    conn.commit()
    conn.close()

    flash(
        "Order status updated successfully.",
        "success"
    )

    return redirect(
        url_for("owner_orders")
    )


# ============================================================
# DELETE OWNER ORDER
# ============================================================

@app.route(
    "/owner-orders/<order_reference>/delete",
    methods=["POST"]
)
def delete_owner_order(
    order_reference
):

    if not ensure_logged_in("owner"):
        return redirect(
            url_for("owner_login")
        )

    shop = get_shop_by_user(
        session["user_id"]
    )

    conn = get_db()

    try:

        conn.execute(
            """
            DELETE FROM payments

            WHERE order_reference = ?
            """,
            (order_reference,)
        )

        conn.execute(
            """
            DELETE FROM orders

            WHERE shop_id = ?
            AND order_reference = ?
            """,
            (
                shop["id"],
                order_reference
            )
        )

        conn.commit()

    except sqlite3.Error as error:

        conn.rollback()

        flash(
            f"Could not delete order: {error}",
            "error"
        )

    else:

        flash(
            "Order removed from view.",
            "success"
        )

    conn.close()

    return redirect(
        url_for("owner_orders")
    )


# ============================================================
# SHOP PROFILE
# ============================================================

@app.route(
    "/shop/<int:shop_id>"
)
def shop_profile(shop_id):

    conn = get_db()

    shop = conn.execute(
        """
        SELECT *
        FROM shops
        WHERE id = ?
        """,
        (shop_id,)
    ).fetchone()

    conn.close()

    if not shop:

        flash(
            "Shop not found.",
            "error"
        )

        return redirect(
            url_for("customer_dashboard")
        )

    return render_template(
        "shop_profile.html",
        shop=shop
    )


# ============================================================
# DATABASE INITIALIZATION
# ============================================================

init_db()


# ============================================================
# APPLICATION START
# ============================================================

if __name__ == "__main__":

    app.run(
        debug=True,
        use_reloader=False,
        host="0.0.0.0",
        port=5000
    )
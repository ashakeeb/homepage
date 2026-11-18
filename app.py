import os
import sqlite3
import re #Regular Expressions search, find, and manipulate text using patterns.
from datetime import datetime
from flask import (
    Flask, render_template, request,
    redirect, session, url_for, flash
)

from database import (
    create_table,
    register_user,
    check_login,
    validate_password,
    get_db_connection
)

app = Flask(__name__)

# Replace this with a long random secret before deployment.
app.secret_key = os.environ.get("SECRET_KEY")

create_table()


@app.route("/")
def home():
    return render_template("index.html")


@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        username = request.form.get("username", "").strip().lower()
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        confirm_password = request.form.get("confirm_password", "")
        role = request.form.get("role", "customer")

        if not all([name, username, email, password, confirm_password]):
            return render_template(
                "register.html",
                error="Please fill in all fields."
            )

        if role not in ("customer", "provider"):
            return render_template(
                "register.html",
                error="Please select a valid account type."
            )

        if not re.fullmatch(r"[a-zA-Z0-9_]{3,20}", username):
            return render_template(
                "register.html",
                error="Username must be 3–20 characters and contain only letters, numbers, or underscores."
            )

        if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email):
            return render_template(
                "register.html",
                error="Please enter a valid email address."
            )

        password_error = validate_password(password)

        if password_error:
            return render_template(
                "register.html",
                error=password_error
            )

        if password != confirm_password:
            return render_template(
                "register.html",
                error="Passwords do not match."
            )

        if register_user(name, username, email, password, role):
            return redirect(url_for("login"))

        return render_template(
            "register.html",
            error="That username or email is already registered."
        )

    return render_template("register.html")


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        identifier = request.form.get("identifier", "").strip().lower()
        password = request.form.get("password", "")

        if not identifier or not password:
            return render_template(
                "login.html",
                error="Please enter your username or email and password."
            )

        user = check_login(identifier, password)

        # Check whether the user exists and the password is correct.
        if user is None:
            return render_template(
                "login.html",
                error="Incorrect username/email or password."
            )

        # Save the user's information in the session.
        session["user_id"] = user["id"]
        session["user_name"] = user["name"]
        session["role"] = user["role"]

        # Redirect according to account type.
        if user["role"] == "provider":
            return redirect(url_for("provider_dashboard"))

        return redirect(url_for("dashboard"))

    return render_template("login.html")


@app.route("/dashboard")
def dashboard():
    if "user_id" not in session:
        return redirect(url_for("login"))

    return render_template(
        "dashboard.html",
        name=session["user_name"]
    )

@app.route("/provider-dashboard")
def provider_dashboard():
    if "user_id" not in session:
        return redirect(url_for("login"))

    if session.get("role") != "provider":
        return redirect(url_for("dashboard"))

    return render_template(
        "provider_dashboard.html",
        name=session["user_name"]
    )
    
@app.route("/provider-appointments")
def provider_appointments():

    if "user_id" not in session:
        return redirect(url_for("login"))

    if session.get("role") != "provider":
        return redirect(url_for("dashboard"))

    db = get_db_connection()

    # Find this provider's appointments.
    appointments = db.execute("""
        SELECT
            bookings.id AS booking_id,
            bookings.appointment_date,
            bookings.status AS booking_status,

            quotes.price,
            quotes.description AS quote_description,

            service_requests.description AS service_description,
            service_requests.location,

            providers.business_name,

            users.name AS customer_name

        FROM bookings

        JOIN quotes
            ON bookings.quote_id = quotes.id

        JOIN providers
            ON quotes.provider_id = providers.id

        JOIN service_requests
            ON quotes.request_id = service_requests.id

        JOIN users
            ON service_requests.customer_id = users.id

        WHERE providers.user_id = ?

        ORDER BY bookings.appointment_date ASC
    """, (session["user_id"],)).fetchall()

    db.close()

    return render_template(
        "provider_appointments.html",
        appointments=appointments
    )
    
@app.route("/update-booking/<int:booking_id>/<action>", methods=["POST"])
def update_booking(booking_id, action):

    # Only logged-in providers can update appointments.
    if "user_id" not in session:
        return redirect(url_for("login"))

    if session.get("role") != "provider":
        return redirect(url_for("dashboard"))

    # Allow only these actions.
    if action not in ("confirm", "reject", "complete"):
        return "Invalid action.", 400

    db = get_db_connection()

    try:
        # Check that this appointment belongs to this provider.
        booking = db.execute("""
            SELECT
                bookings.id,
                bookings.status,
                quotes.id AS quote_id,
                quotes.request_id
            FROM bookings

            JOIN quotes
                ON bookings.quote_id = quotes.id

            JOIN providers
                ON quotes.provider_id = providers.id

            WHERE bookings.id = ?
              AND providers.user_id = ?
        """, (booking_id, session["user_id"])).fetchone()

        if booking is None:
            return "Appointment not found or access denied.", 404

        current_status = booking["status"]

        # Confirm a pending appointment.
        if action == "confirm":

            if current_status != "pending":
                return "Only pending appointments can be confirmed.", 400

            db.execute("""
                UPDATE bookings
                SET status = 'confirmed'
                WHERE id = ?
                  AND status = 'pending'
            """, (booking_id,))

            db.execute("""
                UPDATE service_requests
                SET status = 'confirmed'
                WHERE id = ?
            """, (booking["request_id"],))

        # Reject a pending appointment.
        elif action == "reject":

            if current_status != "pending":
                return "Only pending appointments can be rejected.", 400

            db.execute("""
                UPDATE bookings
                SET status = 'rejected'
                WHERE id = ?
                  AND status = 'pending'
            """, (booking_id,))

            # Reset the selected quote so it is no longer accepted.
            db.execute("""
                UPDATE quotes
                SET status = 'rejected'
                WHERE id = ?
            """, (booking["quote_id"],))

            # Reopen the request so the customer can choose another quote.
            db.execute("""
                UPDATE service_requests
                SET status = 'pending'
                WHERE id = ?
            """, (booking["request_id"],))

        # Mark a confirmed appointment as completed.
        elif action == "complete":

            if current_status != "confirmed":
                return "Only confirmed appointments can be completed.", 400

            db.execute("""
                UPDATE bookings
                SET status = 'completed'
                WHERE id = ?
                  AND status = 'confirmed'
            """, (booking_id,))

            db.execute("""
                UPDATE service_requests
                SET status = 'completed'
                WHERE id = ?
            """, (booking["request_id"],))

        db.commit()

    except sqlite3.Error:
        db.rollback()
        return "Something went wrong while updating the appointment.", 500

    finally:
        db.close()

    return redirect(url_for("provider_appointments"))
    

@app.route("/provider-profile", methods=["GET", "POST"])
def provider_profile():
    if "user_id" not in session:
        return redirect(url_for("login"))

    if session.get("role") != "provider":
        return redirect(url_for("dashboard"))

    db = get_db_connection()

    profile = db.execute("""
        SELECT *
        FROM providers
        WHERE user_id = ?
    """, (session["user_id"],)).fetchone()

    error = None
    success = None

    if request.method == "POST":
        business_name = request.form.get(
            "business_name", ""
        ).strip()

        phone = request.form.get("phone", "").strip()

        description = request.form.get(
            "description", ""
        ).strip()

        if not business_name or not phone:
            error = "Business name and phone number are required."

        elif len(business_name) > 100:
            error = "Business name must be 100 characters or fewer."

        elif len(phone) > 25:
            error = "Phone number must be 25 characters or fewer."

        elif len(description) > 1000:
            error = "Description must be 1000 characters or fewer."

        else:
            if profile:
                db.execute("""
                    UPDATE providers
                    SET business_name = ?,
                        phone = ?,
                        description = ?
                    WHERE user_id = ?
                """, (
                    business_name,
                    phone,
                    description,
                    session["user_id"]
                ))

            else:
                db.execute("""
                    INSERT INTO providers
                        (user_id, business_name, phone, description)
                    VALUES (?, ?, ?, ?)
                """, (
                    session["user_id"],
                    business_name,
                    phone,
                    description
                ))

            db.commit()

            profile = db.execute("""
                SELECT *
                FROM providers
                WHERE user_id = ?
            """, (session["user_id"],)).fetchone()

            success = "Your business profile has been saved."

    db.close()

    return render_template(
        "provider_profile.html",
        profile=profile,
        error=error,
        success=success
    )
    
@app.route("/provider-requests")
def provider_requests():
    if "user_id" not in session:
        return redirect(url_for("login"))

    if session.get("role") != "provider":
        return redirect(url_for("dashboard"))

    db = get_db_connection()

    requests_list = db.execute("""
        SELECT
            service_requests.id,
            categories.name AS category_name,
            service_requests.description,
            service_requests.location,
            service_requests.customer_phone,
            service_requests.status,
            service_requests.created_at
        FROM service_requests
        JOIN categories
            ON service_requests.category_id = categories.id
        WHERE service_requests.status = 'pending'
        ORDER BY service_requests.id DESC
    """).fetchall()

    db.close()

    return render_template(
        "provider_requests.html",
        requests_list=requests_list
    )


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("home"))

@app.route("/request-service", methods=["GET", "POST"])
def request_service():
    if "user_id" not in session:
        return redirect(url_for("login"))

    db = get_db_connection()

    categories = db.execute(
        "SELECT id, name FROM categories ORDER BY name"
    ).fetchall()

    if request.method == "POST":
        category_id = request.form.get("category_id", "").strip()
        description = request.form.get("description", "").strip()
        location = request.form.get("location", "").strip()
        customer_phone = request.form.get("customer_phone", "").strip()

        if not category_id or not description or not location or not customer_phone:
            db.close()
            return render_template(
                "request_service.html",
                categories=categories,
                error="Please complete all fields."
            )

        if len(description) < 10 or len(description) > 1000:
            db.close()
            return render_template(
                "request_service.html",
                categories=categories,
                error="Your description must be between 10 and 1000 characters."
            )

        if len(location) > 200:
            db.close()
            return render_template(
                "request_service.html",
                categories=categories,
                error="Your location must be 200 characters or fewer."
            )

        category = db.execute(
            "SELECT id FROM categories WHERE id = ?",
            (category_id,)
        ).fetchone()

        if not category:
            db.close()
            return render_template(
                "request_service.html",
                categories=categories,
                error="Please select a valid service."
            )

        db.execute("""
            INSERT INTO service_requests
                (customer_id, category_id, description, location, customer_phone, status)
            VALUES (?, ?, ?, ?, ?, 'pending')
        """, (
            session["user_id"],
            category_id,
            description,
            location,
            customer_phone
        ))

        db.commit()
        db.close()

        return redirect(url_for("my_requests"))

    db.close()

    return render_template(
        "request_service.html",
        categories=categories
    )

@app.route("/my-requests")
def my_requests():

    if "user_id" not in session:
        return redirect(url_for("login"))

    db = get_db_connection()

    requests_list = db.execute("""
        SELECT
            service_requests.id,
            categories.name AS category_name,
            service_requests.description,
            service_requests.location,
            service_requests.status,
            service_requests.created_at,

            bookings.appointment_date,
            bookings.status AS booking_status,

            quotes.price,

            providers.business_name,
            providers.phone

        FROM service_requests

        JOIN categories
            ON service_requests.category_id = categories.id

        LEFT JOIN quotes
            ON quotes.request_id = service_requests.id
            AND quotes.status = 'accepted'

        LEFT JOIN bookings
            ON bookings.quote_id = quotes.id

        LEFT JOIN providers
            ON quotes.provider_id = providers.id

        WHERE service_requests.customer_id = ?

        ORDER BY service_requests.id DESC

    """, (session["user_id"],)).fetchall()

    db.close()

    return render_template(
        "my_requests.html",
        requests_list=requests_list
    )
    
@app.route("/submit-quote/<int:request_id>", methods=["GET", "POST"])
def submit_quote(request_id):
    # Only logged-in providers can submit quotes
    if "user_id" not in session:
        return redirect(url_for("login"))

    if session.get("role") != "provider":
        return redirect(url_for("dashboard"))

    db = get_db_connection()

    try:
        # Find the provider's business profile
        provider = db.execute(
            "SELECT id FROM providers WHERE user_id = ?",
            (session["user_id"],)
        ).fetchone()

        if not provider:
            return redirect(url_for("provider_profile"))

        # Find the customer's service request
        service_request = db.execute("""
            SELECT
                service_requests.id,
                categories.name AS category_name,
                service_requests.description,
                service_requests.location,
                service_requests.status
            FROM service_requests
            JOIN categories
                ON service_requests.category_id = categories.id
            WHERE service_requests.id = ?
        """, (request_id,)).fetchone()

        if not service_request:
            return "Service request not found.", 404

        if service_request["status"] != "pending":
            return "This service request is no longer available.", 400

        # Handle quote submission
        if request.method == "POST":
            price_text = request.form.get("price", "").strip()
            description = request.form.get("description", "").strip()

            error = None

            try:
                price = float(price_text)

                if not (0 <= price < float("inf")):
                    error = "Enter a valid price."
            except ValueError:
                price = 0
                error = "Enter a valid price."

            if len(description) > 1000:
                error = "The description must be 1000 characters or fewer."

            if error:
                return render_template(
                    "submit_quote.html",
                    service_request=service_request,
                    error=error
                )

            try:
                db.execute("""
                    INSERT INTO quotes
                        (request_id, provider_id, price, description)
                    VALUES (?, ?, ?, ?)
                """, (
                    request_id,
                    provider["id"],
                    price,
                    description
                ))

                db.commit()
                return redirect(url_for("provider_requests"))

            except sqlite3.IntegrityError:
                db.rollback()

                return render_template(
                    "submit_quote.html",
                    service_request=service_request,
                    error="You have already submitted a quote for this request."
                )

        return render_template(
            "submit_quote.html",
            service_request=service_request,
            error=None
        )

    finally:
        db.close()
@app.route("/my-quotes/<int:request_id>")
def my_quotes(request_id):
    # Customer must be logged in
    if "user_id" not in session:
        return redirect(url_for("login"))

    # Only customers can view quotes for their requests
    if session.get("role") != "customer":
        return redirect(url_for("dashboard"))

    db = get_db_connection()

    try:
        # Make sure this request belongs to the logged-in customer
        service_request = db.execute("""
            SELECT
                sr.id,
                sr.description,
                sr.location,
                c.name AS category_name
            FROM service_requests AS sr
            JOIN categories AS c
                ON sr.category_id = c.id
            WHERE sr.id = ? AND sr.customer_id = ?
        """, (request_id, session["user_id"])).fetchone()

        if not service_request:
            return "Service request not found.", 404

        # Get quotes and provider business details
        quotes = db.execute("""
            SELECT
                q.id,
                q.price,
                q.description AS quote_description,
                q.status AS quote_status,
                q.created_at,
                p.business_name,
                p.phone,
                p.description AS business_description
            FROM quotes AS q
            JOIN providers AS p
                ON q.provider_id = p.id
            WHERE q.request_id = ?
            ORDER BY q.price ASC
        """, (request_id,)).fetchall()

        return render_template(
            "my_quotes.html",
            service_request=service_request,
            quotes=quotes
        )

    finally:
        db.close()

@app.route("/book-appointment/<int:quote_id>", methods=["GET", "POST"])
def book_appointment(quote_id):

    if "user_id" not in session:
        return redirect(url_for("login"))

    if session.get("role") != "customer":
        return redirect(url_for("index"))

    db = get_db_connection()

    # Find the quote and check that it belongs to this customer.
    quote = db.execute("""
        SELECT
            quotes.id,
            quotes.request_id,
            quotes.price,
            quotes.description AS quote_description,
            quotes.status,
            providers.business_name,
            providers.phone,
            providers.description AS provider_description,
            service_requests.customer_id
        FROM quotes
        JOIN providers
            ON quotes.provider_id = providers.id
        JOIN service_requests
            ON quotes.request_id = service_requests.id
        WHERE quotes.id = ?
    """, (quote_id,)).fetchone()

    if quote is None or quote["customer_id"] != session["user_id"]:
        db.close()
        return "Quote not found or access denied.", 404

    # Only pending quotes can be booked.
    if quote["status"] != "pending":
        db.close()

        return render_template(
                "quote_error.html"), 400
            
    error = None

    if request.method == "POST":

        appointment_date = request.form.get(
            "appointment_date", ""
        ).strip()

        try:
            appointment = datetime.fromisoformat(appointment_date)

            if appointment <= datetime.now():
                error = "Please select a future date and time."

        except ValueError:
            error = "Please enter a valid appointment date and time."

        if not error:
            try:
                # Begin a transaction.
                db.execute("BEGIN IMMEDIATE")

                # Check whether this service request already has a booking.
                existing_booking = db.execute("""
                    SELECT bookings.id
                    FROM bookings
                    JOIN quotes
                        ON bookings.quote_id = quotes.id
                    WHERE quotes.request_id = ?
                """, (quote["request_id"],)).fetchone()

                if existing_booking:

                    error = "This service request already has a booking."

                    db.rollback()

                else:

                    # Create the booking.
                    db.execute("""
                        INSERT INTO bookings
                            (quote_id, appointment_date, status)
                        VALUES (?, ?, 'pending')
                    """, (
                        quote_id,
                        appointment.strftime("%Y-%m-%d %H:%M:%S")
                    ))

                    # Accept the selected quote.
                    db.execute("""
                        UPDATE quotes
                        SET status = 'accepted'
                        WHERE id = ?
                    """, (quote_id,))
                    
                    # Mark the service request as confirmed.
                    db.execute("""
                        UPDATE service_requests
                        SET status = 'confirmed'
                        WHERE id = ?
                    """, (quote["request_id"],))

                    # Reject the other quotes for this request.
                    db.execute("""
                        UPDATE quotes
                        SET status = 'rejected'
                        WHERE request_id = ?
                          AND id != ?
                    """, (quote["request_id"], quote_id))

                    db.commit()

                    db.close()

                    return redirect(url_for("my_requests"))

            except sqlite3.IntegrityError:
                db.rollback()
                error = "This quote has already been booked."

            except sqlite3.Error:
                db.rollback()
                error = "Something went wrong. Please try again."

    db.close()

    return render_template(
        "book_appointment.html",
        quote=quote,
        error=error
    )
    
if __name__ == "__main__":
    app.run(debug=False)

from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_user, logout_user, login_required
import re

from app import db
from app.models import User, Preference


# =========================================================
# AUTH BLUEPRINT
# =========================================================

auth_bp = Blueprint(
    "auth",
    __name__,
    url_prefix="/auth"
)


# =========================================================
# DUT EMAIL VALIDATION
# =========================================================
#
# Valid format:
#
# 220578387@dut4life.ac.za
#
# Requirements:
# - Student number must contain exactly 9 digits
# - Must use @dut4life.ac.za
#
# Examples:
#
# 220578387@dut4life.ac.za  -> VALID
# 123456789@dut4life.ac.za  -> VALID
# 12345678@dut4life.ac.za   -> INVALID
# 1234567890@dut4life.ac.za -> INVALID
# 220578387@gmail.com       -> INVALID
#
# =========================================================

DUT_EMAIL_REGEX = re.compile(
    r"^[0-9]{9}@dut4life\.ac\.za$",
    re.IGNORECASE
)


def is_valid_dut_email(email):
    """
    Check whether the email is a valid DUT student email.

    Required format:
    9 digits + @dut4life.ac.za
    """

    return DUT_EMAIL_REGEX.fullmatch(email) is not None


# =========================================================
# REGISTER
# =========================================================

@auth_bp.route("/register", methods=["GET", "POST"])
def register():

    # -----------------------------------------------------
    # Display registration page
    # -----------------------------------------------------

    if request.method == "GET":
        return render_template("auth/register.html")


    # -----------------------------------------------------
    # Get form data
    # -----------------------------------------------------

    name = request.form.get("name", "").strip()

    email = request.form.get(
        "email",
        ""
    ).strip().lower()

    password = request.form.get(
        "password",
        ""
    )

    confirm_password = request.form.get(
        "confirm_password",
        ""
    )


    # =====================================================
    # VALIDATION
    # =====================================================

    # -----------------------------------------------------
    # Validate name
    # -----------------------------------------------------

    if not name:

        flash(
            "Please enter your full name.",
            "danger"
        )

        return redirect(
            url_for("auth.register")
        )


    # -----------------------------------------------------
    # Validate email is not empty
    # -----------------------------------------------------

    if not email:

        flash(
            "Please enter your DUT student email address.",
            "danger"
        )

        return redirect(
            url_for("auth.register")
        )


    # -----------------------------------------------------
    # Validate DUT email format
    # -----------------------------------------------------

    if not is_valid_dut_email(email):

        flash(
            "Please use a valid DUT student email. "
            "Your email must contain exactly 9 digits "
            "followed by @dut4life.ac.za. "
            "Example: 220578387@dut4life.ac.za",
            "danger"
        )

        return redirect(
            url_for("auth.register")
        )


    # -----------------------------------------------------
    # Validate password
    # -----------------------------------------------------

    if not password:

        flash(
            "Please enter a password.",
            "danger"
        )

        return redirect(
            url_for("auth.register")
        )


    # -----------------------------------------------------
    # Validate password length
    # -----------------------------------------------------

    if len(password) < 6:

        flash(
            "Password must contain at least 6 characters.",
            "danger"
        )

        return redirect(
            url_for("auth.register")
        )


    # -----------------------------------------------------
    # Validate password confirmation
    # -----------------------------------------------------

    if not confirm_password:

        flash(
            "Please confirm your password.",
            "danger"
        )

        return redirect(
            url_for("auth.register")
        )


    # -----------------------------------------------------
    # Check passwords match
    # -----------------------------------------------------

    if password != confirm_password:

        flash(
            "Passwords do not match.",
            "danger"
        )

        return redirect(
            url_for("auth.register")
        )


    # =====================================================
    # CHECK IF USER ALREADY EXISTS
    # =====================================================

    existing_user = User.query.filter_by(
        email=email
    ).first()


    if existing_user:

        flash(
            "An account with this DUT email already exists.",
            "warning"
        )

        return redirect(
            url_for("auth.login")
        )


    # =====================================================
    # CREATE USER
    # =====================================================

    try:

        user = User(
            name=name,
            email=email
        )

        # Hash the password using your User model
        user.set_password(password)

        db.session.add(user)

        # Generate the user ID before creating preferences
        db.session.flush()


        # =================================================
        # CREATE DEFAULT SHOPPING PREFERENCES
        # =================================================

        preference = Preference(
            user_id=user.id,
            styles="",
            colours="",
            stores="",
            hobbies=""
        )

        db.session.add(preference)


        # =================================================
        # SAVE EVERYTHING
        # =================================================

        db.session.commit()


    except Exception as e:

        # Roll back if anything goes wrong
        db.session.rollback()

        print(
            f"Registration error: {e}"
        )

        flash(
            "An error occurred while creating your account. "
            "Please try again.",
            "danger"
        )

        return redirect(
            url_for("auth.register")
        )


    # =====================================================
    # REGISTRATION SUCCESS
    # =====================================================

    flash(
        "Registration successful. You can now log in.",
        "success"
    )

    return redirect(
        url_for("auth.login")
    )


# =========================================================
# LOGIN
# =========================================================

@auth_bp.route("/login", methods=["GET", "POST"])
def login():

    if request.method == "POST":

        # -------------------------------------------------
        # Get login information
        # -------------------------------------------------

        email = request.form.get(
            "email",
            ""
        ).strip().lower()

        password = request.form.get(
            "password",
            ""
        )


        # -------------------------------------------------
        # Validate empty email
        # -------------------------------------------------

        if not email:

            flash(
                "Please enter your DUT student email.",
                "danger"
            )

            return render_template(
                "auth/login.html"
            )


        # -------------------------------------------------
        # Validate empty password
        # -------------------------------------------------

        if not password:

            flash(
                "Please enter your password.",
                "danger"
            )

            return render_template(
                "auth/login.html"
            )


        # =================================================
        # FIND USER
        # =================================================

        user = User.query.filter_by(
            email=email
        ).first()


        # =================================================
        # CHECK PASSWORD
        # =================================================

        if user and user.check_password(password):

            login_user(user)


            flash(
                f"Welcome back, {user.name}!",
                "success"
            )


            return redirect(
                url_for("main.dashboard")
            )


        # -------------------------------------------------
        # Invalid login
        # -------------------------------------------------

        flash(
            "Invalid DUT student email or password.",
            "danger"
        )


    # =====================================================
    # DISPLAY LOGIN PAGE
    # =====================================================

    return render_template(
        "auth/login.html"
    )


# =========================================================
# LOGOUT
# =========================================================

@auth_bp.route("/logout")
@login_required
def logout():

    logout_user()


    flash(
        "You have been logged out successfully.",
        "success"
    )


    return redirect(
        url_for("main.index")
    )

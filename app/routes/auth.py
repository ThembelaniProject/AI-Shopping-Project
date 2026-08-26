from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_user, logout_user, login_required

from app import db
from app.models import User, Preference


auth_bp = Blueprint(
    "auth",
    __name__,
    url_prefix="/auth"
)


# =========================================================
# REGISTER
# =========================================================

@auth_bp.route("/register", methods=["GET", "POST"])
def register():

    if request.method == "POST":

        name = request.form.get("name", "").strip()
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        confirm_password = request.form.get("confirm_password", "")

        # ---------------------------------------------
        # Validation
        # ---------------------------------------------

        if not name:
            flash("Please enter your name.", "danger")
            return redirect(url_for("auth.register"))

        if not email:
            flash("Please enter your email address.", "danger")
            return redirect(url_for("auth.register"))

        if not password:
            flash("Please enter a password.", "danger")
            return redirect(url_for("auth.register"))

        if password != confirm_password:
            flash("Passwords do not match.", "danger")
            return redirect(url_for("auth.register"))

        if len(password) < 6:
            flash(
                "Password must contain at least 6 characters.",
                "danger"
            )
            return redirect(url_for("auth.register"))

        # ---------------------------------------------
        # Check if email already exists
        # ---------------------------------------------

        existing_user = User.query.filter_by(
            email=email
        ).first()

        if existing_user:
            flash(
                "An account with this email already exists.",
                "warning"
            )
            return redirect(url_for("auth.login"))

        # ---------------------------------------------
        # Create user
        # ---------------------------------------------

        user = User(
            name=name,
            email=email
        )

        user.set_password(password)

        db.session.add(user)
        db.session.flush()

        # ---------------------------------------------
        # Create default preferences
        # ---------------------------------------------

        preference = Preference(
            user_id=user.id,
            styles="",
            colours="",
            stores="",
            hobbies=""
        )

        db.session.add(preference)

        db.session.commit()

        flash(
            "Registration successful. You can now log in.",
            "success"
        )

        return redirect(url_for("auth.login"))

    return render_template("auth/register.html")


# =========================================================
# LOGIN
# =========================================================

@auth_bp.route("/login", methods=["GET", "POST"])
def login():

    if request.method == "POST":

        email = request.form.get(
            "email",
            ""
        ).strip().lower()

        password = request.form.get(
            "password",
            ""
        )

        # ---------------------------------------------
        # Find user
        # ---------------------------------------------

        user = User.query.filter_by(
            email=email
        ).first()

        # ---------------------------------------------
        # Validate login
        # ---------------------------------------------

        if user and user.check_password(password):

            login_user(user)

            flash(
                f"Welcome back, {user.name}!",
                "success"
            )

            return redirect(
                url_for("main.dashboard")
            )

        flash(
            "Invalid email or password.",
            "danger"
        )

    return render_template("auth/login.html")


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
from flask import (
    Blueprint,
    render_template,
    request,
    redirect,
    url_for,
    flash
)

from flask_login import (
    login_required,
    current_user
)

from app import db
from app.models import Preference


preferences_bp = Blueprint(
    "preferences",
    __name__,
    url_prefix="/preferences"
)


# =========================================================
# USER PREFERENCES
# =========================================================

@preferences_bp.route(
    "/",
    methods=["GET", "POST"]
)
@login_required
def preferences():

    # =====================================================
    # Find existing preferences
    # =====================================================

    preference = Preference.query.filter_by(
        user_id=current_user.id
    ).first()

    # =====================================================
    # SAVE PREFERENCES
    # =====================================================

    if request.method == "POST":

        styles = request.form.get(
            "styles",
            ""
        ).strip()

        colours = request.form.get(
            "colours",
            ""
        ).strip()

        stores = request.form.get(
            "stores",
            ""
        ).strip()

        hobbies = request.form.get(
            "hobbies",
            ""
        ).strip()

        # =================================================
        # Create preferences if they don't exist
        # =================================================

        if preference is None:

            preference = Preference(
                user_id=current_user.id
            )

            db.session.add(
                preference
            )

        # =================================================
        # Update preferences
        # =================================================

        preference.styles = styles

        preference.colours = colours

        preference.stores = stores

        preference.hobbies = hobbies

        # =================================================
        # Save to database
        # =================================================

        db.session.commit()

        flash(
            "Your preferences have been saved successfully.",
            "success"
        )

        return redirect(
            url_for(
                "preferences.preferences"
            )
        )

    # =====================================================
    # Display preferences page
    # =====================================================

    return render_template(
        "preferences.html",
        preference=preference
    )
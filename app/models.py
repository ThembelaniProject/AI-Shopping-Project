from datetime import datetime

from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash

from app import db


# =========================================================
# USER MODEL
# =========================================================

class User(UserMixin, db.Model):

    __tablename__ = "users"

    id = db.Column(
        db.Integer,
        primary_key=True
    )

    name = db.Column(
        db.String(120),
        nullable=False
    )

    email = db.Column(
        db.String(150),
        unique=True,
        nullable=False
    )

    password_hash = db.Column(
        db.String(255),
        nullable=False
    )

    created_at = db.Column(
        db.DateTime,
        default=datetime.utcnow
    )

    # Relationships
    preference = db.relationship(
        "Preference",
        backref="user",
        uselist=False,
        cascade="all, delete-orphan"
    )

    favourites = db.relationship(
        "Favourite",
        backref="user",
        cascade="all, delete-orphan"
    )

    purchases = db.relationship(
        "Purchase",
        backref="user",
        cascade="all, delete-orphan"
    )

    # -----------------------------------------------------
    # Password functions
    # -----------------------------------------------------

    def set_password(self, password):

        self.password_hash = generate_password_hash(
            password
        )

    def check_password(self, password):

        return check_password_hash(
            self.password_hash,
            password
        )


# =========================================================
# PREFERENCE MODEL
# =========================================================

class Preference(db.Model):

    __tablename__ = "preferences"

    id = db.Column(
        db.Integer,
        primary_key=True
    )

    user_id = db.Column(
        db.Integer,
        db.ForeignKey("users.id"),
        unique=True,
        nullable=False
    )

    styles = db.Column(
        db.String(500),
        default=""
    )

    colours = db.Column(
        db.String(500),
        default=""
    )

    stores = db.Column(
        db.String(500),
        default=""
    )

    hobbies = db.Column(
        db.String(500),
        default=""
    )


# =========================================================
# PRODUCT MODEL
# =========================================================

class Product(db.Model):

    __tablename__ = "products"

    id = db.Column(
        db.Integer,
        primary_key=True
    )

    name = db.Column(
        db.String(180),
        nullable=False
    )

    brand = db.Column(
        db.String(100),
        nullable=False
    )

    category = db.Column(
        db.String(100),
        nullable=False
    )

    price = db.Column(
        db.Float,
        nullable=False
    )

    colour = db.Column(
        db.String(60),
        default=""
    )

    size = db.Column(
        db.String(60),
        default=""
    )

    shipping_cost = db.Column(
        db.Float,
        default=0
    )

    store = db.Column(
        db.String(120),
        nullable=False
    )

    location = db.Column(
        db.String(120),
        nullable=False
    )

    latitude = db.Column(
        db.Float,
        default=0
    )

    longitude = db.Column(
        db.Float,
        default=0
    )

    description = db.Column(
        db.Text,
        default=""
    )

    stock = db.Column(
        db.Integer,
        default=0
    )

    source = db.Column(
        db.String(120),
        default="Local Store"
    )

    # -----------------------------------------------------
    # Calculate total cost
    # -----------------------------------------------------

    @property
    def total_cost(self):

        return self.price + self.shipping_cost


# =========================================================
# FAVOURITE MODEL
# =========================================================

class Favourite(db.Model):

    __tablename__ = "favourites"

    id = db.Column(
        db.Integer,
        primary_key=True
    )

    user_id = db.Column(
        db.Integer,
        db.ForeignKey("users.id"),
        nullable=False
    )

    product_id = db.Column(
        db.Integer,
        db.ForeignKey("products.id"),
        nullable=False
    )

    created_at = db.Column(
        db.DateTime,
        default=datetime.utcnow
    )

    product = db.relationship(
        "Product"
    )


# =========================================================
# PURCHASE MODEL
# =========================================================

class Purchase(db.Model):

    __tablename__ = "purchases"

    id = db.Column(
        db.Integer,
        primary_key=True
    )

    user_id = db.Column(
        db.Integer,
        db.ForeignKey("users.id"),
        nullable=False
    )

    product_id = db.Column(
        db.Integer,
        db.ForeignKey("products.id"),
        nullable=False
    )

    quantity = db.Column(
        db.Integer,
        default=1
    )

    purchased_at = db.Column(
        db.DateTime,
        default=datetime.utcnow
    )

    product = db.relationship(
        "Product"
    )
from app import create_app, db
from app.models import Product


products = [
    Product(
        name="Student Laptop 15",
        brand="TechPro",
        category="Laptop",
        price=8999.00,
        colour="Silver",
        size="15-inch",
        shipping_cost=250.00,
        store="TechWorld",
        location="Durban",
        latitude=-29.8587,
        longitude=31.0218,
        description="Affordable laptop suitable for university students and programming.",
        stock=15,
        source="TechWorld"
    ),

    Product(
        name="Budget Laptop 14",
        brand="CompuMax",
        category="Laptop",
        price=7499.00,
        colour="Black",
        size="14-inch",
        shipping_cost=200.00,
        store="Computer Store",
        location="Durban",
        latitude=-29.8587,
        longitude=31.0218,
        description="Compact laptop for studying, browsing and everyday work.",
        stock=10,
        source="Computer Store"
    ),

    Product(
        name="Wireless Headphones",
        brand="SoundMax",
        category="Audio",
        price=899.00,
        colour="Black",
        size="Standard",
        shipping_cost=80.00,
        store="TechWorld",
        location="Durban",
        latitude=-29.8587,
        longitude=31.0218,
        description="Wireless headphones with comfortable ear cushions.",
        stock=30,
        source="TechWorld"
    ),

    Product(
        name="Student Backpack",
        brand="CampusGear",
        category="Bag",
        price=599.00,
        colour="Blue",
        size="Large",
        shipping_cost=60.00,
        store="Campus Store",
        location="Durban",
        latitude=-29.8600,
        longitude=31.0300,
        description="Durable backpack suitable for laptops, books and university equipment.",
        stock=25,
        source="Campus Store"
    ),

    Product(
        name="Running Shoes",
        brand="SportFit",
        category="Shoes",
        price=1299.00,
        colour="White",
        size="9",
        shipping_cost=100.00,
        store="Sports Shop",
        location="Durban",
        latitude=-29.8700,
        longitude=31.0200,
        description="Lightweight running shoes for exercise and everyday use.",
        stock=20,
        source="Sports Shop"
    ),

    Product(
        name="Gaming Mouse",
        brand="GameTech",
        category="Computer Accessories",
        price=499.00,
        colour="Black",
        size="Standard",
        shipping_cost=50.00,
        store="TechWorld",
        location="Durban",
        latitude=-29.8587,
        longitude=31.0218,
        description="Ergonomic mouse suitable for gaming and computer work.",
        stock=40,
        source="TechWorld"
    ),

    Product(
        name="Mechanical Keyboard",
        brand="GameTech",
        category="Computer Accessories",
        price=899.00,
        colour="Black",
        size="Full Size",
        shipping_cost=70.00,
        store="Computer Store",
        location="Durban",
        latitude=-29.8600,
        longitude=31.0300,
        description="Mechanical keyboard suitable for programming and gaming.",
        stock=18,
        source="Computer Store"
    ),

    Product(
        name="USB-C Flash Drive 128GB",
        brand="DataStore",
        category="Storage",
        price=299.00,
        colour="Silver",
        size="128GB",
        shipping_cost=40.00,
        store="Computer Store",
        location="Durban",
        latitude=-29.8600,
        longitude=31.0300,
        description="Portable storage device for university documents and files.",
        stock=50,
        source="Computer Store"
    ),

    Product(
        name="Smartphone 128GB",
        brand="MobileTech",
        category="Smartphone",
        price=4999.00,
        colour="Blue",
        size="6.5-inch",
        shipping_cost=150.00,
        store="Mobile Store",
        location="Durban",
        latitude=-29.8500,
        longitude=31.0100,
        description="Affordable smartphone with 128GB storage.",
        stock=12,
        source="Mobile Store"
    ),

    Product(
        name="Student Hoodie",
        brand="CampusWear",
        category="Clothing",
        price=699.00,
        colour="Black",
        size="Medium",
        shipping_cost=70.00,
        store="Campus Store",
        location="Durban",
        latitude=-29.8600,
        longitude=31.0300,
        description="Comfortable hoodie suitable for students and casual wear.",
        stock=35,
        source="Campus Store"
    ),

    Product(
        name="USB Desk Lamp",
        brand="HomeTech",
        category="Study Equipment",
        price=349.00,
        colour="White",
        size="Standard",
        shipping_cost=50.00,
        store="Home Store",
        location="Durban",
        latitude=-29.8400,
        longitude=31.0200,
        description="Adjustable USB desk lamp for studying.",
        stock=22,
        source="Home Store"
    ),

    Product(
        name="Bluetooth Speaker",
        brand="SoundMax",
        category="Audio",
        price=799.00,
        colour="Red",
        size="Portable",
        shipping_cost=80.00,
        store="TechWorld",
        location="Durban",
        latitude=-29.8587,
        longitude=31.0218,
        description="Portable Bluetooth speaker for music and entertainment.",
        stock=17,
        source="TechWorld"
    ),
]


def seed_database():

    app = create_app()

    with app.app_context():

        existing_products = Product.query.count()

        if existing_products > 0:
            print("Products already exist.")
            return

        db.session.add_all(products)

        db.session.commit()

        print(f"{len(products)} products added successfully.")


if __name__ == "__main__":
    seed_database()
# 🛒 SmartSpend — AI Shopping Assistant

SmartSpend is an **Artificial Intelligence Shopping Assistant** designed to help students save time and make better purchasing decisions.

The application allows students to enter their **budget**, describe what they are looking for, and search for relevant products from multiple retail sources. Products can be filtered and sorted according to **price, colour, size, shipping cost, store, location, and distance**.

SmartSpend also uses a user's **shopping preferences and purchase history** to provide more personalised product recommendations.

---

## 🎓 Project Overview

Students often have limited budgets and need to compare products across different stores before making a purchasing decision.

SmartSpend addresses this problem by bringing product-search and budgeting functionality into one web application.

A student can:

1. Enter their available shopping budget.
2. Describe the product they are looking for.
3. Search products from multiple sources.
4. Compare prices between stores.
5. Filter results according to personal requirements.
6. Search for stores/products within a selected distance.
7. Save shopping preferences.
8. View previous purchases.
9. Receive personalised AI recommendations.
10. Track their remaining monthly shopping budget.

The application is particularly suited to students who need to manage limited monthly allowances.

---

## ✨ Main Features

### 🔍 AI Product Search

Users can enter a natural product request such as:

```text
gaming keyboard
laptop
Nike shoes
headphones
phone
clothing
```

The system searches connected product sources and returns matching products.

---

### 💰 Budget Management

Users can define their available shopping budget.

SmartSpend can display:

* Monthly budget
* Amount spent
* Remaining amount
* Product prices
* Affordable products

Example:

```text
Monthly Budget:    R1,650.00
Spent:               R450.00
Remaining:         R1,200.00
```

The remaining amount is used to help users avoid selecting products outside their available budget.

---

### 💵 Price Comparison

Products from different stores can be displayed together so that users can compare prices.

The application supports sorting such as:

```text
Lowest Price → Highest Price
Highest Price → Lowest Price
```

Sale prices and regular prices are also handled where retailer data provides them.

---

### 🎨 Product Filters

Users can refine their search using:

* Colour
* Size
* Store
* Location
* Shipping cost
* Maximum distance
* Budget

For example:

```text
Product:       Running Shoes
Budget:        R800
Colour:        Black
Size:          9
Distance:      25 km
Store:         Pick n Pay
```

---

### 📍 Location-Based Shopping

SmartSpend can use the user's browser location to determine their approximate shopping location.

Users can search for products or stores within a selected radius, for example:

```text
Maximum Distance: 25 km
```

The application can also reverse-geocode coordinates to display the user's address.

Location information can be used to help identify nearby stores and improve shopping recommendations.

---

### 🏪 Multiple Retail Sources

SmartSpend uses a retailer-provider architecture so that product information can be collected from multiple sources.

The current architecture supports integrations/fallbacks for:

* AZ Labs
* Checkers
* Pick n Pay
* Parse.bot
* LoyaltyHub
* OpenStreetMap / Overpass for location-related information

The application normalises product information into a common format so that products from different sources can be compared.

---

## 🤖 AI Recommendation System

One of the main features of SmartSpend is its personalised recommendation system.

The recommendation engine considers information such as:

* User's preferred colours
* Preferred stores
* Preferred styles
* Hobbies
* Search keywords
* Product category
* Brand
* Product rating
* Stock availability
* Sale status
* Product price

Products receive a recommendation score and matching products can be ranked higher.

### Example

A user may have these preferences:

```text
Preferred Colour: Black
Preferred Store: Checkers
Style: Sporty
Hobby: Gaming
```

When the user searches for a product, SmartSpend analyses the available products and can prioritise products matching those preferences.

The system also records matched preferences so that the user can understand why a product may be considered relevant.

---

## 🧠 Personalisation

Users can configure shopping preferences including:

### Styles

Examples:

```text
Casual
Formal
Sporty
Streetwear
Smart Casual
```

### Colours

Examples:

```text
Black
Blue
White
Red
```

### Stores

Examples:

```text
Checkers
Pick n Pay
```

### Hobbies

Examples:

```text
Gaming
Football
Music
Fitness
Travel
Photography
```

These preferences are used by the recommendation engine when ranking products.

---

## 🛍️ Purchase History

SmartSpend maintains a purchase-history system that can record previous purchases.

Purchase information can be used for:

* Spending analysis
* Monthly budget calculations
* Purchase history
* Personalisation
* Future recommendation improvements

This creates the foundation for a recommendation system that can become increasingly personalised as more shopping activity is recorded.

---

## 👤 Student-Focused Authentication

The application is designed for students and supports account authentication.

The project includes functionality for:

* User registration
* Login
* Logout
* Password management
* Microsoft authentication
* DUT student email validation
* Terms acceptance
* User profiles

DUT student email addresses follow the application's student-email validation rules.

---

## 📊 Dashboard

The dashboard provides an overview of the user's shopping activity.

It includes:

* Monthly budget
* Monthly spending
* Remaining budget
* Purchase history
* AI shopping search
* Product categories
* Shopping features
* AI recommendation information

---

## 📱 Responsive Design

SmartSpend is designed to work across different screen sizes.

The interface supports:

* Desktop computers
* Laptops
* Tablets
* Mobile phones

Responsive styling includes flexible grids, responsive navigation, mobile-friendly forms and touch-friendly controls.

---

# 🏗️ Technology Stack

## Backend

* Python
* Django 6.1

## Database

* PostgreSQL
* Neon PostgreSQL

## Frontend

* HTML5
* CSS3
* JavaScript
* Bootstrap
* Django Templates

## APIs / External Services

* AZ Labs
* Parse.bot
* LoyaltyHub
* OpenStreetMap
* Nominatim
* Overpass

## Authentication

* Django Authentication
* Microsoft OAuth

---

# 📁 Project Structure

A simplified structure of the application is:

```text
AI-Shopping-Project/
│
├── accounts/
│   ├── models.py
│   ├── views.py
│   ├── urls.py
│   └── ...
│
├── products/
│   ├── views.py
│   ├── urls.py
│   ├── models.py
│   │
│   └── services/
│       └── store_api.py
│
├── preferences/
│   ├── models.py
│   ├── views.py
│   ├── urls.py
│   └── ...
│
├── shopping/
│   ├── models.py
│   ├── views.py
│   ├── urls.py
│   └── ...
│
├── templates/
│   ├── base.html
│   ├── dashboard.html
│   ├── accounts/
│   ├── products/
│   ├── preferences/
│   └── shopping/
│
├── static/
│   └── css/
│       └── responsive.css
│
├── manage.py
├── requirements.txt
└── README.md
```

---

# ⚙️ Installation

## 1. Clone the Repository

```bash
git clone https://github.com/ThembelaniProject/AI-Shopping-Project.git
```

Enter the project directory:

```bash
cd AI-Shopping-Project
```

---

## 2. Create a Virtual Environment

Windows:

```powershell
python -m venv venv
```

Activate it:

```powershell
venv\Scripts\Activate.ps1
```

If PowerShell blocks the activation script:

```powershell
Set-ExecutionPolicy -Scope Process RemoteSigned
```

Then:

```powershell
venv\Scripts\Activate.ps1
```

---

## 3. Install Dependencies

```bash
pip install -r requirements.txt
```

---

# 🔐 Environment Variables

Create a `.env` file in the project root.

Example:

```env
DEBUG=True

SECRET_KEY=your-secret-key

DATABASE_URL=your-postgresql-database-url

AZLABS_API_KEY=your-azlabs-api-key
PARSE_API_KEY=your-parse-api-key
LOYALTYHUB_API_KEY=your-loyaltyhub-api-key

RETAILER_API_PROVIDER=azlabs
```

### Important

Do **not** commit API keys, passwords, database credentials or OAuth secrets to GitHub.

The `.env` file should be included in `.gitignore`.

---

# 🗄️ Database Setup

Run Django migrations:

```bash
python manage.py makemigrations
```

Then:

```bash
python manage.py migrate
```

Create an administrator account:

```bash
python manage.py createsuperuser
```

Follow the prompts.

---

# ▶️ Running the Application

Start the Django development server:

```bash
python manage.py runserver
```

Open:

```text
http://127.0.0.1:8000/
```

---

# 🔎 Example Search

A typical SmartSpend search might look like:

```text
Keyword:
Gaming Keyboard

Budget:
R1,000

Colour:
Black

Store:
Checkers

Maximum Distance:
25 km

Sort:
Lowest Price
```

The application then searches available product sources and presents matching results.

---


---

# 📍 Location Architecture

Location information can flow through the application as:

```text
Browser
   │
   ▼
Latitude + Longitude
   │
   ▼
Django
   │
   ├── Store distance
   │
   ├── Radius filtering
   │
   └── Reverse geocoding
             │
             ▼
        User Address
```

OpenStreetMap/Nominatim can be used for reverse geocoding.

---

# 💡 Example Use Case

### Scenario

A student has:

```text
Available budget: R1,650
```

They need:

```text
Black running shoes
```

They specify:

```text
Colour: Black
Size: 9
Maximum distance: 25 km
Sort: Lowest price
```

SmartSpend can then:

1. Search connected product sources.
2. Retrieve matching products.
3. Normalise product information.
4. Apply the student's filters.
5. Check product prices against the budget.
6. Consider store/location information.
7. Apply personalised recommendation scoring.
8. Rank relevant products.
9. Display the available products for comparison.

---

# 🎯 Project Objectives

The main objectives of SmartSpend are to:

* Reduce the time students spend searching for products.
* Help students stay within their budgets.
* Compare prices across different stores.
* Find products within a chosen geographic area.
* Personalise shopping recommendations.
* Use previous shopping information to improve future recommendations.
* Provide a centralised shopping search experience.
* Demonstrate the practical application of artificial intelligence in e-commerce.

---

# 🔒 Security Considerations

The application uses Django's security mechanisms and should be configured with:

* Secure passwords
* Environment variables for secrets
* CSRF protection
* Authentication
* Authorisation
* Secure database credentials
* HTTPS in production
* Secure OAuth configuration
* Input validation

API keys must never be hard-coded into source files.

---

# 🚀 Future Improvements

Potential future improvements include:

### Advanced Machine Learning

Train recommendation models using:

* Purchase history
* Search history
* Click behaviour
* Saved products
* Product categories
* Price preferences

### More Retailers

Additional South African retailers could be integrated into the provider architecture.

### Smarter Natural-Language Search

Users could enter:

```text
I have R1500 and need a laptop for programming and university work.
```

The system could extract:

```text
Budget: R1500
Category: Laptop
Purpose: Programming / University
```

and automatically construct the search.

### Price History

Track historical prices and identify:

```text
Current price
Previous price
Lowest recorded price
Price change
```

### Better Recommendation Explanations

The application could explain:

```text
Why this product is recommended

✓ Matches your preferred colour
✓ Within your budget
✓ Available nearby
✓ Matches your preferred store
✓ Similar to previous purchases
```

---

# 🧪 Testing

Before deployment, test:

* Registration
* Login
* Microsoft authentication
* Password handling
* Budget calculations
* Product searching
* Price sorting
* Colour filtering
* Size filtering
* Shipping filtering
* Store filtering
* Distance filtering
* Location permissions
* Address lookup
* Purchase history
* Preferences
* AI recommendations
* Mobile responsiveness
* API failures and rate limits

---

# ⚠️ API Availability

Product availability depends on the connected external APIs.

If a provider is unavailable, rate-limited or returns no products, SmartSpend may use another configured provider or display an appropriate error message.

External retailer APIs may change their:

* Endpoints
* Authentication
* Response formats
* Rate limits
* Product availability

The provider architecture is designed to reduce the impact of these changes.

---

# 👨‍💻 Development

This project was developed as an AI Shopping application focused on helping students make faster and more informed shopping decisions.

The project demonstrates practical use of:

* Web application development
* Artificial intelligence
* Recommendation systems
* Database management
* API integration
* Location services
* Budget management
* User personalisation
* Responsive web design

---

# 📄 Academic Project

**Project:** AI Shopping Application

**Purpose:**
Develop an AI-powered shopping assistant that helps students save time and make informed purchasing decisions based on their budget, preferences, location and shopping requirements.

**Target Users:**
Students, particularly students managing limited monthly budgets.

---

# 📜 License

This project is intended for educational and development purposes.

---

# 👤 Author


GitHub:

https://github.com/ThembelaniProject

Repository:

https://github.com/ThembelaniProject/AI-Shopping-Project

Live Site: 

https://smartspend-black.vercel.app/

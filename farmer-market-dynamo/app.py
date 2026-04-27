from flask import Flask, render_template, request, jsonify, redirect, url_for, flash, session
from werkzeug.security import generate_password_hash, check_password_hash
from functools import wraps
import uuid, os, boto3, json
from datetime import datetime
from boto3.dynamodb.conditions import Key, Attr
from botocore.exceptions import ClientError
from decimal import Decimal   # ✅ FIX

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'farmmarket-secret-2024')

AWS_REGION    = os.environ.get('AWS_REGION', 'ap-south-1')

dynamodb = boto3.resource('dynamodb', region_name=AWS_REGION)

users_table    = dynamodb.Table('fm_users')
products_table = dynamodb.Table('fm_products')
orders_table   = dynamodb.Table('fm_orders')
reviews_table  = dynamodb.Table('fm_reviews')
cart_table     = dynamodb.Table('fm_cart')

# ✅ convert Decimal → float for UI
def convert_decimals(obj):
    if isinstance(obj, list):
        return [convert_decimals(i) for i in obj]
    elif isinstance(obj, dict):
        return {k: convert_decimals(v) for k, v in obj.items()}
    elif isinstance(obj, Decimal):
        return float(obj)
    return obj

def scan_table(table, filter_expr=None):
    kwargs = {}
    if filter_expr:
        kwargs['FilterExpression'] = filter_expr
    items = []
    while True:
        resp = table.scan(**kwargs)
        items.extend(resp.get('Items', []))
        if 'LastEvaluatedKey' not in resp:
            break
        kwargs['ExclusiveStartKey'] = resp['LastEvaluatedKey']
    return items

def current_user():
    uid = session.get('user_id')
    if not uid:
        return None
    resp = users_table.get_item(Key={'user_id': uid})
    return resp.get('Item')

# ================= HOME =================
@app.route('/')
def index():
    all_products = scan_table(products_table, Attr('status').eq('active'))
    all_products = convert_decimals(all_products)   # ✅ FIX

    all_products.sort(key=lambda x: x.get('created_at', ''), reverse=True)

    all_users  = scan_table(users_table)
    all_orders = scan_table(orders_table)

    stats = {
        'farmers':   sum(1 for u in all_users if u.get('role') == 'farmer'),
        'products':  len(all_products),
        'consumers': sum(1 for u in all_users if u.get('role') == 'consumer'),
        'orders':    len(all_orders),
    }

    return render_template('index.html', products=all_products[:8], stats=stats)

# ================= LOGIN =================
@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form['email']
        password = request.form['password']

        users = scan_table(users_table)
        user = next((u for u in users if u['email'] == email), None)

        if user and check_password_hash(user['password'], password):
            session['user_id'] = user['user_id']
            return redirect(url_for('index'))

        flash('Invalid credentials')

    return render_template('login.html')

# ================= REGISTER =================
@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        user = {
            'user_id': str(uuid.uuid4()),
            'name': request.form['name'],
            'email': request.form['email'],
            'password': generate_password_hash(request.form['password']),
            'role': request.form['role'],
            'created_at': datetime.utcnow().isoformat()
        }

        users_table.put_item(Item=user)
        return redirect(url_for('login'))

    return render_template('register.html')

# ================= ADD PRODUCT =================
@app.route('/add-product', methods=['POST'])
def add_product():
    product = {
        'product_id': str(uuid.uuid4()),
        'name': request.form['name'],
        'price': Decimal(request.form['price']),   # ✅ FIX
        'unit': request.form['unit'],
        'stock': int(request.form['stock']),
        'avg_rating': Decimal("0.0"),              # ✅ FIX
        'status': 'active',
        'created_at': datetime.utcnow().isoformat()
    }

    products_table.put_item(Item=product)
    return redirect(url_for('index'))

# ================= CHECKOUT =================
@app.route('/checkout', methods=['POST'])
def checkout():
    items = request.json.get('items', [])

    for item in items:
        order = {
            'order_id': str(uuid.uuid4()),
            'product_id': item['product_id'],
            'price_per_unit': Decimal(str(item['price'])),
            'quantity': int(item['quantity']),
            'total_price': Decimal(str(item['price'])) * int(item['quantity']),  # ✅ FIX
            'ordered_at': datetime.utcnow().isoformat()
        }
        orders_table.put_item(Item=order)

    return jsonify({'message': 'Order placed'})

# ================= REVIEW =================
@app.route('/review/<product_id>', methods=['POST'])
def add_review(product_id):
    rating = int(request.form['rating'])

    review = {
        'review_id': str(uuid.uuid4()),
        'product_id': product_id,
        'rating': rating,
        'created_at': datetime.utcnow().isoformat()
    }

    reviews_table.put_item(Item=review)

    all_reviews = scan_table(reviews_table, Attr('product_id').eq(product_id))
    avg = sum(int(r['rating']) for r in all_reviews) / len(all_reviews)

    products_table.update_item(
        Key={'product_id': product_id},
        UpdateExpression='SET avg_rating = :a',
        ExpressionAttributeValues={
            ':a': Decimal(str(round(avg, 1)))   # ✅ FIX
        }
    )

    return redirect(url_for('index'))

# ================= SEED =================
def seed():
    resp = users_table.scan(Limit=1)
    if resp.get('Count', 0) > 0:
        return

    sample_products = [
        {
            'product_id': str(uuid.uuid4()),
            'name': 'Tomato',
            'price': Decimal("40"),
            'unit': 'kg',
            'stock': 100,
            'avg_rating': Decimal("4.5"),
            'status': 'active',
            'created_at': datetime.utcnow().isoformat()
        }
    ]

    for p in sample_products:
        products_table.put_item(Item=p)

if __name__ == '__main__':
    seed()
    app.run(host='0.0.0.0', port=5000, debug=True)

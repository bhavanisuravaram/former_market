from flask import Flask, render_template, request, jsonify, redirect, url_for, flash, session
from werkzeug.security import generate_password_hash, check_password_hash
from functools import wraps
import uuid, os, boto3, json
from datetime import datetime
from boto3.dynamodb.conditions import Key, Attr
from decimal import Decimal   # ✅ IMPORTANT

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'farmmarket-secret-2024')

AWS_REGION = 'ap-south-1'

dynamodb = boto3.resource('dynamodb', region_name=AWS_REGION)

users_table    = dynamodb.Table('fm_users')
products_table = dynamodb.Table('fm_products')
orders_table   = dynamodb.Table('fm_orders')
reviews_table  = dynamodb.Table('fm_reviews')
cart_table     = dynamodb.Table('fm_cart')

# ================= SAFE CONVERSION =================
def convert_decimals(obj):
    if isinstance(obj, list):
        return [convert_decimals(i) for i in obj]
    elif isinstance(obj, dict):
        return {k: convert_decimals(v) for k, v in obj.items()}
    elif isinstance(obj, Decimal):
        return float(obj)
    return obj

# ================= SCAN =================
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

# ================= HOME =================
@app.route('/')
def index():
    all_products = scan_table(products_table, Attr('status').eq('active'))
    all_products = convert_decimals(all_products)

    all_products.sort(key=lambda x: x.get('created_at', ''), reverse=True)

    # ✅ ADD THIS BLOCK
    all_users = scan_table(users_table)
    all_orders = scan_table(orders_table)

    stats = {
        'farmers':   sum(1 for u in all_users if u.get('role') == 'farmer'),
        'products':  len(all_products),
        'consumers': sum(1 for u in all_users if u.get('role') == 'consumer'),
        'orders':    len(all_orders),
    }

    return render_template(
        'index.html',
        products=all_products[:8],
        stats=stats   # ✅ THIS FIXES YOUR ERROR
    )

# ================= PRODUCTS =================
@app.route('/products')
def products():
    all_products = scan_table(products_table, Attr('status').eq('active'))
    all_products = convert_decimals(all_products)

    all_products.sort(key=lambda p: p.get('price', 0))

    return render_template('products.html', products=all_products)

# ================= ADD PRODUCT =================
@app.route('/add-product', methods=['POST'])
def add_product():
    product = {
        'product_id': str(uuid.uuid4()),
        'name': request.form['name'],
        'price': Decimal(request.form['price']),   # ✅ FIXED
        'unit': request.form['unit'],
        'stock': int(request.form['stock']),
        'avg_rating': Decimal("0.0"),              # ✅ FIXED
        'status': 'active',
        'created_at': datetime.utcnow().isoformat()
    }

    products_table.put_item(Item=product)
    return redirect(url_for('index'))

# ================= CART =================
@app.route('/cart')
def cart():
    items = []
    total = sum(Decimal(i['price']) * int(i['quantity']) for i in items)
    return render_template('cart.html', items=items, total=float(total))

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
            'total_price': Decimal(str(item['price'])) * int(item['quantity']),
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
            ':a': Decimal(str(round(avg, 1)))   # ✅ FIXED
        }
    )

    return redirect(url_for('index'))

# ================= SEED =================
def seed():
    resp = users_table.scan(Limit=1)
    if resp.get('Count', 0) > 0:
        return

    print("Seeding data...")

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
        },
        {
            'product_id': str(uuid.uuid4()),
            'name': 'Spinach',
            'price': Decimal("30"),
            'unit': 'bunch',
            'stock': 50,
            'avg_rating': Decimal("4.8"),
            'status': 'active',
            'created_at': datetime.utcnow().isoformat()
        }
    ]

    for p in sample_products:
        products_table.put_item(Item=p)

    print("Seed done!")

# ================= MAIN =================
if __name__ == '__main__':
    seed()
    app.run(host='0.0.0.0', port=5000, debug=True)

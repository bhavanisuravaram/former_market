from flask import Flask, render_template, request, jsonify, redirect, url_for, flash, session
from werkzeug.security import generate_password_hash, check_password_hash
from functools import wraps
import uuid, os, boto3, json
from datetime import datetime
from boto3.dynamodb.conditions import Key, Attr
from botocore.exceptions import ClientError
from decimal import Decimal   # ✅ ADDED

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'farmmarket-secret-2024')

AWS_REGION    = os.environ.get('AWS_REGION', 'ap-south-1')
SNS_TOPIC_ARN = os.environ.get('SNS_TOPIC_ARN', '')
S3_BUCKET     = os.environ.get('S3_BUCKET', '')
SQS_QUEUE_URL = os.environ.get('SQS_QUEUE_URL', '')

dynamodb = boto3.resource('dynamodb', region_name=AWS_REGION)

users_table    = dynamodb.Table('fm_users')
products_table = dynamodb.Table('fm_products')
orders_table   = dynamodb.Table('fm_orders')
reviews_table  = dynamodb.Table('fm_reviews')
cart_table     = dynamodb.Table('fm_cart')

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

def login_required(f):
    @wraps(f)
    def dec(*a, **kw):
        if not session.get('user_id'):
            return redirect(url_for('login'))
        return f(*a, **kw)
    return dec

# ================== FIX 1: add_product ==================
@app.route('/farmer/add-product', methods=['GET', 'POST'])
@login_required
def add_product():
    if request.method == 'POST':
        product = {
            'product_id': str(uuid.uuid4()),
            'name': request.form['name'],
            'price': Decimal(request.form['price']),   # ✅ FIXED
            'unit': request.form['unit'],
            'stock': int(request.form['stock']),
            'avg_rating': Decimal("0.0"),              # ✅ FIXED
            'created_at': datetime.utcnow().isoformat(),
            'status': 'active'
        }
        products_table.put_item(Item=product)
        return redirect(url_for('index'))
    return "Add Product Page"

# ================== FIX 2: checkout ==================
@app.route('/checkout', methods=['POST'])
@login_required
def checkout():
    items = request.json.get('items', [])
    for item in items:
        order = {
            'order_id': str(uuid.uuid4()),
            'product_id': item['product_id'],
            'price_per_unit': Decimal(str(item['price'])),   # ✅ FIXED
            'quantity': int(item['quantity']),
            'total_price': Decimal(str(item['price'])) * int(item['quantity']),  # ✅ FIXED
            'ordered_at': datetime.utcnow().isoformat()
        }
        orders_table.put_item(Item=order)
    return jsonify({'message': 'Order placed'})

# ================== FIX 3: review ==================
@app.route('/review/<product_id>', methods=['POST'])
@login_required
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

# ================== FIX 4: SEED DATA ==================
def seed():
    resp = users_table.scan(Limit=1)
    if resp.get('Count', 0) > 0:
        return

    fid1 = str(uuid.uuid4())

    sample_products = [
        {
            'product_id': str(uuid.uuid4()),
            'name': 'Tomato',
            'price': Decimal("40"),         # ✅ FIXED
            'unit': 'kg',
            'stock': 100,
            'avg_rating': Decimal("4.5"),   # ✅ FIXED
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

    print("Seed completed")

# ================== MAIN ==================
if __name__ == '__main__':
    seed()
    app.run(host='0.0.0.0', port=5000, debug=True)

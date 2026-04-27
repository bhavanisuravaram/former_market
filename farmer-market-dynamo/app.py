from flask import Flask, render_template, request, jsonify, redirect, url_for, flash, session
from werkzeug.security import generate_password_hash, check_password_hash
from functools import wraps
import uuid, os, boto3, json
from datetime import datetime
from boto3.dynamodb.conditions import Key, Attr
from botocore.exceptions import ClientError
from decimal import Decimal  # ✅ FIXED: needed for DynamoDB numeric storage

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'farmmarket-secret-2024')

AWS_REGION    = os.environ.get('AWS_REGION', 'ap-south-1')
SNS_TOPIC_ARN = os.environ.get('SNS_TOPIC_ARN', '')   # ✅ RESTORED
S3_BUCKET     = os.environ.get('S3_BUCKET', '')        # ✅ RESTORED
SQS_QUEUE_URL = os.environ.get('SQS_QUEUE_URL', '')    # ✅ RESTORED

# ── DynamoDB tables ────────────────────────────────────────────────────────────
dynamodb = boto3.resource('dynamodb', region_name=AWS_REGION)

users_table    = dynamodb.Table('fm_users')
products_table = dynamodb.Table('fm_products')
orders_table   = dynamodb.Table('fm_orders')
reviews_table  = dynamodb.Table('fm_reviews')
cart_table     = dynamodb.Table('fm_cart')

# ── Decimal converter (DynamoDB returns Decimal, templates need float) ─────────
# ✅ FIXED: prevents "Object of type Decimal is not JSON serializable" errors
def convert_decimals(obj):
    if isinstance(obj, list):
        return [convert_decimals(i) for i in obj]
    elif isinstance(obj, dict):
        return {k: convert_decimals(v) for k, v in obj.items()}
    elif isinstance(obj, Decimal):
        return float(obj)
    return obj

# ── DynamoDB scan helper ───────────────────────────────────────────────────────
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

# ── Auth helpers ───────────────────────────────────────────────────────────────
def current_user():
    uid = session.get('user_id')
    if not uid:
        return None
    try:
        resp = users_table.get_item(Key={'user_id': uid})
        item = resp.get('Item')
        return convert_decimals(item) if item else None  # ✅ FIXED: convert before returning
    except Exception:
        return None

# ✅ RESTORED: all three decorators were missing from app(2).py
def login_required(f):
    @wraps(f)
    def dec(*a, **kw):
        if not session.get('user_id'):
            flash('Please login to continue.', 'error')
            return redirect(url_for('login'))
        return f(*a, **kw)
    return dec

def farmer_required(f):
    @wraps(f)
    def dec(*a, **kw):
        u = current_user()
        if not u or u.get('role') != 'farmer':
            flash('Farmer access only.', 'error')
            return redirect(url_for('index'))
        return f(*a, **kw)
    return dec

def consumer_required(f):
    @wraps(f)
    def dec(*a, **kw):
        u = current_user()
        if not u or u.get('role') != 'consumer':
            flash('Consumer access only.', 'error')
            return redirect(url_for('index'))
        return f(*a, **kw)
    return dec

# ── AWS service helpers ────────────────────────────────────────────────────────
# ✅ RESTORED: all four helpers were missing from app(2).py

def sns_notify(subject, message):
    if not SNS_TOPIC_ARN:
        return
    try:
        boto3.client('sns', region_name=AWS_REGION).publish(
            TopicArn=SNS_TOPIC_ARN, Subject=subject, Message=message)
    except Exception:
        pass

def upload_to_s3(file_obj, filename):
    if not S3_BUCKET:
        return None
    try:
        key = f"products/{uuid.uuid4()}_{filename}"
        boto3.client('s3', region_name=AWS_REGION).upload_fileobj(
            file_obj, S3_BUCKET, key, ExtraArgs={'ACL': 'public-read'})
        return f"https://{S3_BUCKET}.s3.{AWS_REGION}.amazonaws.com/{key}"
    except Exception:
        return None

def enqueue_order(order_data):
    if not SQS_QUEUE_URL:
        return
    try:
        boto3.client('sqs', region_name=AWS_REGION).send_message(
            QueueUrl=SQS_QUEUE_URL, MessageBody=json.dumps(order_data, default=str))
    except Exception:
        pass

def put_metric(name, value=1):
    try:
        boto3.client('cloudwatch', region_name=AWS_REGION).put_metric_data(
            Namespace='FarmerMarketplace',
            MetricData=[{'MetricName': name, 'Value': value, 'Unit': 'Count'}])
    except Exception:
        pass

# ══════════════════════════════════════════════════════════════════════════════
#  ROUTES
# ══════════════════════════════════════════════════════════════════════════════

# ── Home ───────────────────────────────────────────────────────────────────────
@app.route('/')
def index():
    all_products = scan_table(products_table, Attr('status').eq('active'))
    all_products = convert_decimals(all_products)  # ✅ FIXED: Decimal → float
    all_products.sort(key=lambda x: x.get('created_at', ''), reverse=True)
    products = all_products[:8]
    featured = [p for p in all_products if p.get('featured')][:4]  # ✅ RESTORED
    cats     = list({p.get('category', '') for p in all_products if p.get('category')})  # ✅ RESTORED

    all_users  = scan_table(users_table)
    all_orders = scan_table(orders_table)
    stats = {
        'farmers':   sum(1 for u in all_users if u.get('role') == 'farmer'),
        'products':  len(all_products),
        'consumers': sum(1 for u in all_users if u.get('role') == 'consumer'),
        'orders':    len(all_orders),
    }
    user = current_user()
    return render_template('index.html', products=products, featured=featured,
                           categories=cats, user=user, stats=stats)

# ── Products listing ───────────────────────────────────────────────────────────
@app.route('/products')
def products():
    search   = request.args.get('search', '')    # ✅ RESTORED: search/filter/sort
    category = request.args.get('category', '')
    sort_by  = request.args.get('sort', 'newest')

    all_products = scan_table(products_table, Attr('status').eq('active'))
    all_products = convert_decimals(all_products)  # ✅ FIXED: Decimal → float

    if search:
        s = search.lower()
        all_products = [p for p in all_products
                        if s in p.get('name', '').lower()
                        or s in p.get('farmer_name', '').lower()]
    if category:
        all_products = [p for p in all_products if p.get('category') == category]

    sort_map = {
        'newest':     (lambda p: p.get('created_at', ''), True),
        'price_low':  (lambda p: float(p.get('price', 0)), False),
        'price_high': (lambda p: float(p.get('price', 0)), True),
        'rating':     (lambda p: float(p.get('avg_rating', 0)), True),
    }
    key_fn, reverse = sort_map.get(sort_by, sort_map['newest'])
    all_products.sort(key=key_fn, reverse=reverse)

    cats = list({p.get('category', '') for p in
                 convert_decimals(scan_table(products_table, Attr('status').eq('active')))
                 if p.get('category')})
    user = current_user()
    return render_template('products.html', products=all_products, categories=cats,
                           search=search, category=category, sort_by=sort_by, user=user)

# ── Product detail ─────────────────────────────────────────────────────────────
# ✅ RESTORED: entire route was missing from app(2).py
@app.route('/product/<product_id>')
def product_detail(product_id):
    resp = products_table.get_item(Key={'product_id': product_id})
    product = resp.get('Item')
    if not product:
        flash('Product not found.', 'error')
        return redirect(url_for('products'))
    product = convert_decimals(product)  # ✅ FIXED

    reviews = scan_table(reviews_table, Attr('product_id').eq(product_id))
    reviews = convert_decimals(reviews)
    reviews.sort(key=lambda x: x.get('created_at', ''), reverse=True)

    farmer_resp = users_table.get_item(Key={'user_id': product.get('farmer_id', '')})
    farmer = convert_decimals(farmer_resp.get('Item'))
    user   = current_user()
    put_metric('ProductViews')
    return render_template('product_detail.html', product=product,
                           reviews=reviews, farmer=farmer, user=user)

# ── Farmers listing ────────────────────────────────────────────────────────────
# ✅ RESTORED: entire route was missing from app(2).py
@app.route('/farmers')
def farmers():
    all_farmers  = convert_decimals(scan_table(users_table, Attr('role').eq('farmer')))
    all_products = convert_decimals(scan_table(products_table, Attr('status').eq('active')))
    for f in all_farmers:
        f['product_count'] = sum(1 for p in all_products if p.get('farmer_id') == f['user_id'])
    user = current_user()
    return render_template('farmers.html', farmers=all_farmers, user=user)

# ── Register ───────────────────────────────────────────────────────────────────
@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        email = request.form['email'].strip().lower()
        # ✅ RESTORED: email uniqueness check was missing from app(2).py
        existing = scan_table(users_table, Attr('email').eq(email))
        if existing:
            flash('Email already registered.', 'error')
            return redirect(url_for('register'))
        role = request.form['role']
        user = {
            'user_id':   str(uuid.uuid4()),
            'name':      request.form['name'].strip(),
            'email':     email,
            'password':  generate_password_hash(request.form['password']),
            'role':      role,
            'phone':     request.form.get('phone', ''),      # ✅ RESTORED
            'location':  request.form.get('location', ''),   # ✅ RESTORED
            'farm_name': request.form.get('farm_name', '') if role == 'farmer' else '',  # ✅ RESTORED
            'bio':       '',
            'verified':  False,
            'joined_at': datetime.utcnow().isoformat(),
        }
        users_table.put_item(Item=user)
        session['user_id'] = user['user_id']
        session['role']    = role  # ✅ RESTORED: role missing from session in app(2).py
        sns_notify('New User Registered', f"New {role}: {user['name']} ({email})")
        put_metric('NewRegistrations')
        flash(f"Welcome, {user['name']}!", 'success')
        # ✅ RESTORED: redirect to correct dashboard based on role
        return redirect(url_for('farmer_dashboard') if role == 'farmer' else url_for('consumer_dashboard'))
    return render_template('register.html', user=None)

# ── Login ──────────────────────────────────────────────────────────────────────
@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email    = request.form['email'].strip().lower()
        password = request.form['password']
        matches  = scan_table(users_table, Attr('email').eq(email))
        u = matches[0] if matches else None
        if u and check_password_hash(u['password'], password):
            session['user_id'] = u['user_id']
            session['role']    = u['role']  # ✅ RESTORED
            flash(f"Welcome back, {u['name']}!", 'success')
            return redirect(url_for('farmer_dashboard') if u['role'] == 'farmer' else url_for('consumer_dashboard'))
        flash('Invalid credentials.', 'error')
    return render_template('login.html', user=None)

# ── Logout ─────────────────────────────────────────────────────────────────────
# ✅ RESTORED: entire route was missing from app(2).py
@app.route('/logout')
def logout():
    session.clear()
    flash('Logged out.', 'success')
    return redirect(url_for('index'))

# ── Farmer dashboard ───────────────────────────────────────────────────────────
# ✅ RESTORED: entire route was missing from app(2).py
@app.route('/farmer/dashboard')
@login_required
@farmer_required
def farmer_dashboard():
    user  = current_user()
    prods = convert_decimals(scan_table(products_table, Attr('farmer_id').eq(user['user_id'])))
    prods.sort(key=lambda x: x.get('created_at', ''), reverse=True)
    orders = convert_decimals(scan_table(orders_table, Attr('farmer_id').eq(user['user_id'])))
    orders.sort(key=lambda x: x.get('ordered_at', ''), reverse=True)
    stats = {
        'total_products':  len(prods),
        'active_products': sum(1 for p in prods if p.get('status') == 'active'),
        'total_orders':    len(orders),
        'pending_orders':  sum(1 for o in orders if o.get('status') == 'pending'),
        'total_revenue':   sum(float(o.get('total_price', 0)) for o in orders if o.get('status') != 'cancelled'),
    }
    return render_template('farmer_dashboard.html', user=user,
                           products=prods[:5], orders=orders[:5], stats=stats)

# ── Add product ────────────────────────────────────────────────────────────────
# ✅ FIXED: app(2).py had wrong URL, no auth, missing fields, no S3 upload
@app.route('/farmer/add-product', methods=['GET', 'POST'])
@login_required
@farmer_required
def add_product():
    user = current_user()
    if request.method == 'POST':
        image_url = '/static/images/default-product.jpg'
        if 'image' in request.files:
            f = request.files['image']
            if f.filename:
                url = upload_to_s3(f, f.filename)
                if url:
                    image_url = url
        product = {
            'product_id':   str(uuid.uuid4()),
            'farmer_id':    user['user_id'],
            'farmer_name':  user['name'],
            'farm_name':    user.get('farm_name', ''),
            'name':         request.form['name'],
            'description':  request.form['description'],
            'category':     request.form['category'],
            'price':        Decimal(str(request.form['price'])),  # ✅ FIXED: use Decimal for DynamoDB
            'unit':         request.form['unit'],
            'stock':        int(request.form['stock']),
            'image_url':    image_url,
            'organic':      'organic' in request.form,
            'featured':     False,
            'avg_rating':   Decimal('0'),   # ✅ FIXED: use Decimal for DynamoDB
            'review_count': 0,
            'status':       'active',
            'created_at':   datetime.utcnow().isoformat(),
        }
        products_table.put_item(Item=product)
        sns_notify('New Product Listed',
                   f"{user['name']} listed {product['name']} at Rs.{product['price']}/{product['unit']}")
        put_metric('ProductsListed')
        flash('Product listed successfully!', 'success')
        return redirect(url_for('farmer_dashboard'))
    return render_template('add_product.html', user=user)

# ── My products ────────────────────────────────────────────────────────────────
# ✅ RESTORED: entire route was missing from app(2).py
@app.route('/farmer/my-products')
@login_required
@farmer_required
def my_products():
    user  = current_user()
    prods = convert_decimals(scan_table(products_table, Attr('farmer_id').eq(user['user_id'])))
    prods.sort(key=lambda x: x.get('created_at', ''), reverse=True)
    return render_template('my_products.html', user=user, products=prods)

# ── Farmer orders ──────────────────────────────────────────────────────────────
# ✅ RESTORED: entire route was missing from app(2).py
@app.route('/farmer/orders')
@login_required
@farmer_required
def farmer_orders():
    user   = current_user()
    orders = convert_decimals(scan_table(orders_table, Attr('farmer_id').eq(user['user_id'])))
    orders.sort(key=lambda x: x.get('ordered_at', ''), reverse=True)
    return render_template('farmer_orders.html', user=user, orders=orders)

# ── Update order status ────────────────────────────────────────────────────────
# ✅ RESTORED: entire route was missing from app(2).py
@app.route('/farmer/order/<order_id>/<status>')
@login_required
@farmer_required
def update_order(order_id, status):
    if status not in ['confirmed', 'shipped', 'delivered', 'cancelled']:
        flash('Invalid status.', 'error')
        return redirect(url_for('farmer_orders'))
    orders_table.update_item(
        Key={'order_id': order_id},
        UpdateExpression='SET #s = :s, updated_at = :u',
        ExpressionAttributeNames={'#s': 'status'},
        ExpressionAttributeValues={':s': status, ':u': datetime.utcnow().isoformat()}
    )
    sns_notify(f'Order {status.title()}', f"Order {order_id[:8].upper()} is now {status}.")
    flash(f'Order marked as {status}.', 'success')
    return redirect(url_for('farmer_orders'))

# ── Toggle product active/inactive ─────────────────────────────────────────────
# ✅ RESTORED: entire route was missing from app(2).py
@app.route('/product/toggle/<product_id>')
@login_required
@farmer_required
def toggle_product(product_id):
    resp = products_table.get_item(Key={'product_id': product_id})
    p    = resp.get('Item')
    if p:
        ns = 'inactive' if p.get('status') == 'active' else 'active'
        products_table.update_item(
            Key={'product_id': product_id},
            UpdateExpression='SET #s = :s',
            ExpressionAttributeNames={'#s': 'status'},
            ExpressionAttributeValues={':s': ns}
        )
        flash(f"Product {'activated' if ns == 'active' else 'deactivated'}.", 'success')
    return redirect(url_for('my_products'))

# ── Delete product ─────────────────────────────────────────────────────────────
# ✅ RESTORED: entire route was missing from app(2).py
@app.route('/product/delete/<product_id>')
@login_required
@farmer_required
def delete_product(product_id):
    products_table.delete_item(Key={'product_id': product_id})
    flash('Product deleted.', 'success')
    return redirect(url_for('my_products'))

# ── Consumer dashboard ─────────────────────────────────────────────────────────
# ✅ RESTORED: entire route was missing from app(2).py
@app.route('/consumer/dashboard')
@login_required
@consumer_required
def consumer_dashboard():
    user   = current_user()
    orders = convert_decimals(scan_table(orders_table, Attr('consumer_id').eq(user['user_id'])))
    orders.sort(key=lambda x: x.get('ordered_at', ''), reverse=True)

    resp     = cart_table.get_item(Key={'user_id': user['user_id']})
    cart_doc = resp.get('Item') or {'items': []}
    stats = {
        'total_orders':     len(orders),
        'pending_orders':   sum(1 for o in orders if o.get('status') == 'pending'),
        'delivered_orders': sum(1 for o in orders if o.get('status') == 'delivered'),
        'total_spent':      sum(float(o.get('total_price', 0)) for o in orders),
        'cart_items':       len(cart_doc.get('items', [])),
    }
    return render_template('consumer_dashboard.html', user=user, orders=orders[:5], stats=stats)

# ── Cart ───────────────────────────────────────────────────────────────────────
# ✅ RESTORED: entire route was missing from app(2).py
@app.route('/cart')
@login_required
@consumer_required
def cart():
    user     = current_user()
    resp     = cart_table.get_item(Key={'user_id': user['user_id']})
    cart_doc = resp.get('Item') or {'items': []}
    items    = convert_decimals(cart_doc.get('items', []))  # ✅ FIXED
    total    = sum(float(i['price']) * int(i['quantity']) for i in items)
    return render_template('cart.html', user=user, items=items, total=total)

# ── Add to cart ────────────────────────────────────────────────────────────────
# ✅ RESTORED: entire route was missing from app(2).py
@app.route('/cart/add/<product_id>', methods=['POST'])
@login_required
@consumer_required
def add_to_cart(product_id):
    user = current_user()
    resp = products_table.get_item(Key={'product_id': product_id})
    product = resp.get('Item')
    if not product:
        flash('Product not found.', 'error')
        return redirect(url_for('products'))
    product = convert_decimals(product)
    qty = int(request.form.get('quantity', 1))

    cart_resp = cart_table.get_item(Key={'user_id': user['user_id']})
    cart_doc  = cart_resp.get('Item')
    new_item = {
        'product_id':  product_id,
        'name':        product['name'],
        'price':       Decimal(str(product['price'])),  # ✅ FIXED: store as Decimal in DynamoDB
        'unit':        product['unit'],
        'quantity':    qty,
        'farmer_id':   product.get('farmer_id', ''),
        'farmer_name': product.get('farmer_name', ''),
        'image_url':   product.get('image_url', ''),
    }
    if cart_doc:
        items = cart_doc.get('items', [])
        found = False
        for item in items:
            if item['product_id'] == product_id:
                item['quantity'] = min(int(item['quantity']) + qty, int(product.get('stock', 99)))
                found = True
                break
        if not found:
            items.append(new_item)
        cart_table.update_item(
            Key={'user_id': user['user_id']},
            UpdateExpression='SET items = :i',
            ExpressionAttributeValues={':i': items}
        )
    else:
        cart_table.put_item(Item={'user_id': user['user_id'], 'items': [new_item]})

    flash(f"{product['name']} added to cart!", 'success')
    return redirect(url_for('product_detail', product_id=product_id))

# ── Remove from cart ───────────────────────────────────────────────────────────
# ✅ RESTORED: entire route was missing from app(2).py
@app.route('/cart/remove/<product_id>')
@login_required
@consumer_required
def remove_from_cart(product_id):
    user      = current_user()
    cart_resp = cart_table.get_item(Key={'user_id': user['user_id']})
    cart_doc  = cart_resp.get('Item')
    if cart_doc:
        items = [i for i in cart_doc.get('items', []) if i['product_id'] != product_id]
        cart_table.update_item(
            Key={'user_id': user['user_id']},
            UpdateExpression='SET items = :i',
            ExpressionAttributeValues={':i': items}
        )
    flash('Item removed.', 'success')
    return redirect(url_for('cart'))

# ── Checkout ───────────────────────────────────────────────────────────────────
# ✅ FIXED: app(2).py checkout read from request.json (API style) — restored to cart-based HTML flow
@app.route('/checkout', methods=['GET', 'POST'])
@login_required
@consumer_required
def checkout():
    user      = current_user()
    cart_resp = cart_table.get_item(Key={'user_id': user['user_id']})
    cart_doc  = cart_resp.get('Item')
    if not cart_doc or not cart_doc.get('items'):
        flash('Cart is empty.', 'error')
        return redirect(url_for('products'))
    if request.method == 'POST':
        items = convert_decimals(cart_doc['items'])  # ✅ FIXED
        for item in items:
            order = {
                'order_id':       str(uuid.uuid4()),
                'consumer_id':    user['user_id'],
                'consumer_name':  user['name'],
                'consumer_email': user['email'],
                'farmer_id':      item.get('farmer_id', ''),
                'farmer_name':    item.get('farmer_name', ''),
                'product_id':     item['product_id'],
                'product_name':   item['name'],
                'quantity':       int(item['quantity']),
                'unit':           item['unit'],
                'price_per_unit': Decimal(str(item['price'])),   # ✅ FIXED
                'total_price':    Decimal(str(item['price'])) * int(item['quantity']),  # ✅ FIXED
                'address':        request.form.get('address', ''),
                'phone':          request.form.get('phone', ''),
                'status':         'pending',
                'ordered_at':     datetime.utcnow().isoformat(),
            }
            orders_table.put_item(Item=order)
            # Decrement stock
            products_table.update_item(
                Key={'product_id': item['product_id']},
                UpdateExpression='SET stock = stock - :q',
                ExpressionAttributeValues={':q': int(item['quantity'])}
            )
            enqueue_order({k: str(v) if isinstance(v, Decimal) else v for k, v in order.items()})
            sns_notify('New Order',
                       f"{user['name']} ordered {item['quantity']} {item['unit']} of {item['name']}.")
            put_metric('OrdersPlaced')
        cart_table.delete_item(Key={'user_id': user['user_id']})
        flash(f"Order placed! {len(items)} item(s) ordered.", 'success')
        return redirect(url_for('consumer_dashboard'))
    items = convert_decimals(cart_doc['items'])
    total = sum(float(i['price']) * int(i['quantity']) for i in items)
    return render_template('checkout.html', user=user, items=items, total=total)

# ── Add review ─────────────────────────────────────────────────────────────────
# ✅ RESTORED: entire route was missing from app(2).py
@app.route('/review/<product_id>', methods=['POST'])
@login_required
@consumer_required
def add_review(product_id):
    user = current_user()
    existing = scan_table(reviews_table,
                          Attr('product_id').eq(product_id) & Attr('user_id').eq(user['user_id']))
    if existing:
        flash('Already reviewed.', 'error')
        return redirect(url_for('product_detail', product_id=product_id))
    rating = int(request.form.get('rating', 5))
    review = {
        'review_id':  str(uuid.uuid4()),
        'product_id': product_id,
        'user_id':    user['user_id'],
        'user_name':  user['name'],
        'rating':     rating,
        'comment':    request.form.get('comment', ''),
        'created_at': datetime.utcnow().isoformat(),
    }
    reviews_table.put_item(Item=review)
    all_rev = scan_table(reviews_table, Attr('product_id').eq(product_id))
    avg = sum(int(r.get('rating', 0)) for r in all_rev) / len(all_rev)
    products_table.update_item(
        Key={'product_id': product_id},
        UpdateExpression='SET avg_rating = :a, review_count = :c',
        ExpressionAttributeValues={':a': Decimal(str(round(avg, 1))), ':c': len(all_rev)}  # ✅ FIXED
    )
    flash('Review submitted!', 'success')
    return redirect(url_for('product_detail', product_id=product_id))

# ── Profile ────────────────────────────────────────────────────────────────────
# ✅ RESTORED: entire route was missing from app(2).py
@app.route('/profile', methods=['GET', 'POST'])
@login_required
def profile():
    user = current_user()
    if request.method == 'POST':
        expr = 'SET #n = :n, phone = :p, #loc = :l, bio = :b'
        vals = {
            ':n': request.form['name'],
            ':p': request.form.get('phone', ''),
            ':l': request.form.get('location', ''),
            ':b': request.form.get('bio', ''),
        }
        names = {'#n': 'name', '#loc': 'location'}
        if user['role'] == 'farmer':
            expr += ', farm_name = :f'
            vals[':f'] = request.form.get('farm_name', '')
        users_table.update_item(
            Key={'user_id': user['user_id']},
            UpdateExpression=expr,
            ExpressionAttributeNames=names,
            ExpressionAttributeValues=vals
        )
        flash('Profile updated!', 'success')
        return redirect(url_for('profile'))
    return render_template('profile.html', user=user)

# ── Health check ───────────────────────────────────────────────────────────────
# ✅ RESTORED: route was missing from app(2).py
@app.route('/health')
def health():
    return jsonify({'status': 'healthy', 'service': 'Farmer Marketplace'})

# ══════════════════════════════════════════════════════════════════════════════
#  SEED DATA
# ══════════════════════════════════════════════════════════════════════════════
# ✅ FIXED: app(2).py seed only seeded products and skipped users entirely,
#    which broke the seed-check logic (always empty → re-seeded on every restart)
def seed():
    resp = users_table.scan(Limit=1)
    if resp.get('Count', 0) > 0:
        return
    print("Seeding DynamoDB tables...")
    fid1, fid2 = str(uuid.uuid4()), str(uuid.uuid4())
    users_table.put_item(Item={
        'user_id': fid1, 'name': 'Ramu Reddy', 'email': 'ramu@farmer.com',
        'password': generate_password_hash('password123'), 'role': 'farmer',
        'farm_name': 'Reddy Organic Farm', 'phone': '9876543210',
        'location': 'Warangal, Telangana', 'bio': 'Growing organic vegetables for 20 years.',
        'verified': True, 'joined_at': datetime.utcnow().isoformat()
    })
    users_table.put_item(Item={
        'user_id': fid2, 'name': 'Lakshmi Devi', 'email': 'lakshmi@farmer.com',
        'password': generate_password_hash('password123'), 'role': 'farmer',
        'farm_name': 'Devi Natural Farms', 'phone': '9876543211',
        'location': 'Nalgonda, Telangana', 'bio': 'Specializing in fresh fruits and dairy.',
        'verified': True, 'joined_at': datetime.utcnow().isoformat()
    })
    users_table.put_item(Item={
        'user_id': str(uuid.uuid4()), 'name': 'Arjun Kumar', 'email': 'arjun@consumer.com',
        'password': generate_password_hash('password123'), 'role': 'consumer',
        'phone': '9876543212', 'location': 'Hyderabad', 'bio': '',
        'verified': False, 'joined_at': datetime.utcnow().isoformat()
    })
    sample_products = [
        {'farmer_id': fid1, 'farmer_name': 'Ramu Reddy', 'farm_name': 'Reddy Organic Farm',
         'name': 'Fresh Tomatoes', 'description': 'Farm-fresh organic tomatoes. Hand-picked daily.',
         'category': 'Vegetables', 'price': Decimal('40'), 'unit': 'kg', 'stock': 100,
         'organic': True, 'featured': True, 'avg_rating': Decimal('4.5'), 'review_count': 12,
         'image_url': 'https://images.unsplash.com/photo-1592924357228-91a4daadcfea?w=400', 'status': 'active'},
        {'farmer_id': fid1, 'farmer_name': 'Ramu Reddy', 'farm_name': 'Reddy Organic Farm',
         'name': 'Green Spinach', 'description': 'Fresh spinach harvested this morning.',
         'category': 'Vegetables', 'price': Decimal('30'), 'unit': 'bunch', 'stock': 50,
         'organic': True, 'featured': True, 'avg_rating': Decimal('4.8'), 'review_count': 8,
         'image_url': 'https://images.unsplash.com/photo-1576045057995-568f588f82fb?w=400', 'status': 'active'},
        {'farmer_id': fid2, 'farmer_name': 'Lakshmi Devi', 'farm_name': 'Devi Natural Farms',
         'name': 'Alphonso Mangoes', 'description': 'Premium Alphonso mangoes. Sweet, juicy.',
         'category': 'Fruits', 'price': Decimal('120'), 'unit': 'kg', 'stock': 200,
         'organic': False, 'featured': True, 'avg_rating': Decimal('4.9'), 'review_count': 25,
         'image_url': 'https://images.unsplash.com/photo-1553279768-865429fa0078?w=400', 'status': 'active'},
        {'farmer_id': fid2, 'farmer_name': 'Lakshmi Devi', 'farm_name': 'Devi Natural Farms',
         'name': 'Fresh Cow Milk', 'description': 'Pure A2 cow milk collected fresh every morning.',
         'category': 'Dairy', 'price': Decimal('60'), 'unit': 'litre', 'stock': 30,
         'organic': True, 'featured': False, 'avg_rating': Decimal('4.7'), 'review_count': 18,
         'image_url': 'https://images.unsplash.com/photo-1550583724-b2692b85b150?w=400', 'status': 'active'},
    ]
    for p in sample_products:
        p['product_id'] = str(uuid.uuid4())
        p['created_at'] = datetime.utcnow().isoformat()
        products_table.put_item(Item=p)
    print("Seed done!  ramu@farmer.com / lakshmi@farmer.com / arjun@consumer.com — password: password123")

if __name__ == '__main__':
    seed()
    app.run(host='0.0.0.0', port=5000, debug=True)

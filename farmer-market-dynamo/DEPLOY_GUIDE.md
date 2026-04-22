# Farmer Marketplace — AWS EC2 Deployment Guide
## DynamoDB + EC2 + IAM Role (No Secret Keys)

---

## OVERVIEW

```
Your Browser
     │
     ▼
EC2 Instance  (port 80 → Gunicorn :5000)
     │  IAM Role (automatic credentials)
     ├─► DynamoDB   (fm_users, fm_products, fm_orders, fm_reviews, fm_cart)
     ├─► S3         (product images — optional)
     ├─► SNS        (email notifications — optional)
     └─► SQS        (order queue — optional)
```

No `.aws/credentials` file. No secret keys anywhere.
The EC2 IAM Role gives the app permission to call AWS services automatically.

---

## PART 1 — CREATE IAM ROLE FOR EC2

> Do this in the AWS Console before launching the EC2 instance.

### Step 1.1 — Open IAM
1. Go to **AWS Console → IAM → Roles → Create role**
2. Trusted entity type: **AWS service**
3. Use case: **EC2** → click **Next**

### Step 1.2 — Attach Policies
Search and check each of these managed policies:

| Policy Name | Why |
|---|---|
| `AmazonDynamoDBFullAccess` | Read/write all DynamoDB tables |
| `AmazonS3FullAccess` | Upload product images (or use a custom policy for one bucket) |
| `AmazonSNSFullAccess` | Send notifications |
| `AmazonSQSFullAccess` | Order queue |
| `CloudWatchAgentServerPolicy` | Push custom metrics |

> **Minimum required:** Only `AmazonDynamoDBFullAccess` is needed to run the app.
> The others are needed only if you set SNS_TOPIC_ARN, S3_BUCKET, SQS_QUEUE_URL in .env

Click **Next → Next**

### Step 1.3 — Name the Role
- Role name: `FarmerMarketplaceEC2Role`
- Click **Create role**

---

## PART 2 — LAUNCH EC2 INSTANCE

### Step 2.1 — Open EC2 Console
Go to **AWS Console → EC2 → Instances → Launch instances**

### Step 2.2 — Configure the Instance

| Setting | Value |
|---|---|
| Name | `farmer-marketplace` |
| AMI | **Ubuntu Server 24.04 LTS** (free tier eligible) |
| Instance type | `t2.micro` (free tier) or `t3.small` for better performance |
| Key pair | Create new → name it `farmer-key` → download the `.pem` file |
| VPC | Default VPC |
| Auto-assign public IP | **Enable** |

### Step 2.3 — Security Group
Create a new security group named `farmer-marketplace-sg` with these inbound rules:

| Type | Protocol | Port | Source | Purpose |
|---|---|---|---|---|
| SSH | TCP | 22 | My IP | Admin access |
| HTTP | TCP | 80 | 0.0.0.0/0 | Public web access |
| Custom TCP | TCP | 5000 | 0.0.0.0/0 | Direct Flask access (optional) |

### Step 2.4 — Attach IAM Role
- Expand **Advanced details**
- **IAM instance profile:** Select `FarmerMarketplaceEC2Role`
- Click **Launch instance**

### Step 2.5 — Note the Public IP
After the instance starts (1–2 min), go to **EC2 → Instances** and copy the **Public IPv4 address**.

---

## PART 3 — CONNECT TO EC2

### From Linux/Mac:
```bash
chmod 400 farmer-key.pem
ssh -i farmer-key.pem ubuntu@<YOUR_EC2_PUBLIC_IP>
```

### From Windows (PowerShell):
```powershell
ssh -i farmer-key.pem ubuntu@<YOUR_EC2_PUBLIC_IP>
```

---

## PART 4 — INSTALL DEPENDENCIES ON EC2

Run each command after connecting via SSH:

```bash
# Update system
sudo apt update && sudo apt upgrade -y

# Install Python, pip, nginx, git, unzip
sudo apt install -y python3 python3-pip python3-venv nginx git unzip

# Verify Python version (need 3.8+)
python3 --version
```

---

## PART 5 — UPLOAD AND SET UP THE APP

### Option A — Upload with SCP (from your local machine, NOT inside SSH)
```bash
# On your LOCAL machine:
scp -i farmer-key.pem farmer-marketplace-dynamo.zip ubuntu@<EC2_IP>:~/
```

### Option B — Use Git (if your code is on GitHub)
```bash
# Inside SSH session:
git clone https://github.com/YOUR_USERNAME/farmer-marketplace.git
cd farmer-marketplace
```

### Unzip and enter the project folder (Option A)
```bash
# Inside SSH session:
unzip farmer-marketplace-dynamo.zip
cd farmer-market-dynamo
```

---

## PART 6 — CREATE PYTHON VIRTUAL ENVIRONMENT

```bash
# Still inside the project folder
python3 -m venv venv
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Verify boto3 is installed
python3 -c "import boto3; print('boto3 OK')"
```

---

## PART 7 — CONFIGURE ENVIRONMENT VARIABLES

```bash
# Edit the .env file
nano .env
```

Paste and update these values:
```
SECRET_KEY=your-very-secret-random-key-here
AWS_REGION=ap-south-1
SNS_TOPIC_ARN=                     # Leave blank if not using SNS
S3_BUCKET=                         # Leave blank if not using S3
SQS_QUEUE_URL=                     # Leave blank if not using SQS
```

Save: `Ctrl+O → Enter → Ctrl+X`

---

## PART 8 — CREATE DYNAMODB TABLES

```bash
# Make sure you're in the project folder with venv active
source venv/bin/activate

# Create all 5 DynamoDB tables
python3 create_tables.py
```

Expected output:
```
  Creating fm_users...
  Creating fm_products...
  Creating fm_orders...
  Creating fm_reviews...
  Creating fm_cart...

Waiting for tables to become ACTIVE...
  fm_users is ACTIVE
  fm_products is ACTIVE
  fm_orders is ACTIVE
  fm_reviews is ACTIVE
  fm_cart is ACTIVE

All tables ready!
```

---

## PART 9 — TEST THE APP MANUALLY

```bash
# Load environment variables and run Flask
source venv/bin/activate
python3 app.py
```

You should see:
```
Seeding DynamoDB tables...
Seed done!  ramu@farmer.com / lakshmi@farmer.com / arjun@consumer.com — password: password123
 * Running on http://0.0.0.0:5000
```

Test in browser: `http://<EC2_PUBLIC_IP>:5000`

Stop the app: `Ctrl+C`

---

## PART 10 — SET UP GUNICORN AS A SYSTEMD SERVICE

This keeps the app running even after you close SSH.

### Step 10.1 — Find the full path to gunicorn
```bash
which gunicorn
# Example output: /home/ubuntu/farmer-market-dynamo/venv/bin/gunicorn
```

### Step 10.2 — Create the service file
```bash
sudo nano /etc/systemd/system/farmer-marketplace.service
```

Paste this (update paths if different):
```ini
[Unit]
Description=Farmer Marketplace Flask App
After=network.target

[Service]
User=ubuntu
WorkingDirectory=/home/ubuntu/farmer-market-dynamo
EnvironmentFile=/home/ubuntu/farmer-market-dynamo/.env
ExecStart=/home/ubuntu/farmer-market-dynamo/venv/bin/gunicorn \
    --workers 3 \
    --bind 0.0.0.0:5000 \
    --timeout 120 \
    app:app
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

Save: `Ctrl+O → Enter → Ctrl+X`

### Step 10.3 — Enable and start the service
```bash
sudo systemctl daemon-reload
sudo systemctl enable farmer-marketplace
sudo systemctl start farmer-marketplace

# Check status
sudo systemctl status farmer-marketplace
```

You should see `Active: active (running)`.

### Useful service commands:
```bash
sudo systemctl restart farmer-marketplace   # Restart app
sudo systemctl stop farmer-marketplace      # Stop app
sudo journalctl -u farmer-marketplace -f    # View live logs
```

---

## PART 11 — SET UP NGINX AS REVERSE PROXY (Port 80)

This lets users access the site on port 80 (standard HTTP) instead of :5000.

### Step 11.1 — Create Nginx config
```bash
sudo nano /etc/nginx/sites-available/farmer-marketplace
```

Paste:
```nginx
server {
    listen 80;
    server_name _;

    client_max_body_size 16M;

    location / {
        proxy_pass http://127.0.0.1:5000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    }

    location /static/ {
        alias /home/ubuntu/farmer-market-dynamo/static/;
        expires 30d;
    }
}
```

Save: `Ctrl+O → Enter → Ctrl+X`

### Step 11.2 — Enable the site
```bash
sudo ln -s /etc/nginx/sites-available/farmer-marketplace /etc/nginx/sites-enabled/
sudo rm -f /etc/nginx/sites-enabled/default

# Test nginx config
sudo nginx -t

# Restart nginx
sudo systemctl restart nginx
sudo systemctl enable nginx
```

### Step 11.3 — Test
Open browser: `http://<EC2_PUBLIC_IP>`

The site should load without the `:5000` in the URL.

---

## PART 12 — VERIFY IAM ROLE IS WORKING

From inside the EC2 SSH session:
```bash
# Check role is attached
curl -s http://169.254.169.254/latest/meta-data/iam/security-credentials/

# Test DynamoDB access (should list your tables)
python3 -c "
import boto3
ddb = boto3.client('dynamodb', region_name='ap-south-1')
tables = ddb.list_tables()['TableNames']
print('DynamoDB tables:', tables)
"
```

Expected output: `DynamoDB tables: ['fm_cart', 'fm_orders', 'fm_products', 'fm_reviews', 'fm_users']`

---

## QUICK REFERENCE

| What | Command |
|---|---|
| View app logs | `sudo journalctl -u farmer-marketplace -f` |
| Restart app | `sudo systemctl restart farmer-marketplace` |
| Restart nginx | `sudo systemctl restart nginx` |
| Check app status | `sudo systemctl status farmer-marketplace` |
| SSH into EC2 | `ssh -i farmer-key.pem ubuntu@<EC2_IP>` |
| App URL | `http://<EC2_PUBLIC_IP>` |

## Default Login Credentials (seeded)
| Email | Password | Role |
|---|---|---|
| ramu@farmer.com | password123 | Farmer |
| lakshmi@farmer.com | password123 | Farmer |
| arjun@consumer.com | password123 | Consumer |

---

## DynamoDB Tables Reference

| Table | Primary Key | Purpose |
|---|---|---|
| `fm_users` | `user_id` (String) | All users (farmers & consumers) |
| `fm_products` | `product_id` (String) | Product listings |
| `fm_orders` | `order_id` (String) | All orders |
| `fm_reviews` | `review_id` (String) | Product reviews |
| `fm_cart` | `user_id` (String) | Shopping cart per user |

No GSI on any table. All filtering is done via DynamoDB Scan with FilterExpression in Python.

---

## TROUBLESHOOTING

### App not starting
```bash
sudo journalctl -u farmer-marketplace -n 50
```

### DynamoDB access denied
- Go to EC2 Console → select your instance → Actions → Security → Modify IAM role
- Make sure `FarmerMarketplaceEC2Role` is attached

### Port 5000 not accessible from browser
- Check security group has port 80 (and 5000 if testing directly) open to 0.0.0.0/0
- EC2 Console → Security Groups → Inbound rules

### Nginx 502 Bad Gateway
- The Flask app is not running: `sudo systemctl status farmer-marketplace`
- Restart it: `sudo systemctl restart farmer-marketplace`

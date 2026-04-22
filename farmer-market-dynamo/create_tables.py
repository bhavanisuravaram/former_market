#!/usr/bin/env python3
"""
create_tables.py  —  Run this ONCE on the EC2 instance to create all DynamoDB tables.
Uses the EC2 IAM role automatically (no keys needed).
Usage:  python3 create_tables.py
"""
import boto3, os, time

REGION = os.environ.get('AWS_REGION', 'ap-south-1')
client = boto3.client('dynamodb', region_name=REGION)

TABLES = [
    {
        'TableName': 'fm_users',
        'KeySchema': [{'AttributeName': 'user_id', 'KeyType': 'HASH'}],
        'AttributeDefinitions': [{'AttributeName': 'user_id', 'AttributeType': 'S'}],
        'BillingMode': 'PAY_PER_REQUEST',
    },
    {
        'TableName': 'fm_products',
        'KeySchema': [{'AttributeName': 'product_id', 'KeyType': 'HASH'}],
        'AttributeDefinitions': [{'AttributeName': 'product_id', 'AttributeType': 'S'}],
        'BillingMode': 'PAY_PER_REQUEST',
    },
    {
        'TableName': 'fm_orders',
        'KeySchema': [{'AttributeName': 'order_id', 'KeyType': 'HASH'}],
        'AttributeDefinitions': [{'AttributeName': 'order_id', 'AttributeType': 'S'}],
        'BillingMode': 'PAY_PER_REQUEST',
    },
    {
        'TableName': 'fm_reviews',
        'KeySchema': [{'AttributeName': 'review_id', 'KeyType': 'HASH'}],
        'AttributeDefinitions': [{'AttributeName': 'review_id', 'AttributeType': 'S'}],
        'BillingMode': 'PAY_PER_REQUEST',
    },
    {
        'TableName': 'fm_cart',
        'KeySchema': [{'AttributeName': 'user_id', 'KeyType': 'HASH'}],
        'AttributeDefinitions': [{'AttributeName': 'user_id', 'AttributeType': 'S'}],
        'BillingMode': 'PAY_PER_REQUEST',
    },
]

for tbl in TABLES:
    name = tbl['TableName']
    try:
        client.create_table(**tbl)
        print(f"  Creating {name}...")
    except client.exceptions.ResourceInUseException:
        print(f"  {name} already exists, skipping.")

# Wait for all tables to become ACTIVE
print("\nWaiting for tables to become ACTIVE...")
waiter = client.get_waiter('table_exists')
for tbl in TABLES:
    waiter.wait(TableName=tbl['TableName'])
    print(f"  {tbl['TableName']} is ACTIVE")

print("\nAll tables ready!")

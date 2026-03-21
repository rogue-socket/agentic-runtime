# Sham Payments / Banking API

A mock backend for a payments/banking application with a single pre-existing account (default balance: **₹50,000**).

## Setup

```bash
pip install -r requirements.txt
python app.py
```

The server starts at `http://localhost:5000`.

## API Endpoints

### 1. Check Balance

```
GET /balance
```

**Response:**
```json
{
  "status": "success",
  "account_id": "ACC-001",
  "holder": "John Doe",
  "balance": 50000.0
}
```

---

### 2. Make a Payment

```
POST /pay
Content-Type: application/json
```

**Request body:**

| Field       | Type   | Required | Description                          |
|-------------|--------|----------|--------------------------------------|
| `amount`    | number | Yes      | Amount to pay (must be > 0)          |
| `recipient` | string | Yes      | Website or URL receiving the payment |

**Example request:**
```bash
curl -X POST http://localhost:5000/pay \
  -H "Content-Type: application/json" \
  -d '{"amount": 1500, "recipient": "https://example-shop.com"}'
```

**Success response (200):**
```json
{
  "status": "success",
  "message": "Payment of 1500 to https://example-shop.com completed",
  "balance": 48500.0,
  "transaction": {
    "recipient": "https://example-shop.com",
    "amount": 1500,
    "balance_after": 48500.0
  }
}
```

**Failed response — insufficient funds (402):**
```json
{
  "status": "failed",
  "message": "Insufficient funds",
  "balance": 48500.0,
  "requested": 99999
}
```

---

### 3. Pay for a Shop Order (with shop callback)

Processes payment for an order from the shop on `:8000`. Deducts the amount and sends a confirmation to `POST http://localhost:8000/payments/confirm`.

```
POST /pay/order
Content-Type: application/json
```

**Request body:**

| Field      | Type   | Required | Description                              |
|------------|--------|----------|------------------------------------------|
| `order_id` | string | Yes      | Unique order ID from the shop's checkout |
| `amount`   | number | Yes      | Total amount to pay (must be > 0)        |

**Example request:**
```bash
curl -X POST http://localhost:5000/pay/order \
  -H "Content-Type: application/json" \
  -d '{"order_id": "ord_abc123", "amount": 2500}'
```

**Success response (200):**
```json
{
  "status": "success",
  "message": "Payment of 2500 for order ord_abc123 completed",
  "balance": 47500.0,
  "transaction": {
    "order_id": "ord_abc123",
    "amount": 2500,
    "balance_after": 47500.0
  },
  "shop_notified": true
}
```

**Failed response — insufficient funds (402):**
```json
{
  "status": "failed",
  "message": "Insufficient funds",
  "balance": 100.0,
  "requested": 2500
}
```

The shop is also notified with `"status": "failed"` when funds are insufficient.

---

### 4. View Transaction History

```
GET /transactions
```

**Response:**
```json
{
  "status": "success",
  "account_id": "ACC-001",
  "transactions": [
    {
      "recipient": "https://example-shop.com",
      "amount": 1500,
      "balance_after": 48500.0
    }
  ]
}
```

---

### 5. Reset Account

Restores the account balance to 50,000 and clears all transactions.

```
POST /reset
```

**Response:**
```json
{
  "status": "success",
  "message": "Account reset to default balance",
  "balance": 50000.0
}
```

## Error Codes

| HTTP Code | Meaning                                      |
|-----------|----------------------------------------------|
| 200       | Request succeeded                            |
| 400       | Bad request (missing fields or invalid data) |
| 402       | Payment failed — insufficient funds          |

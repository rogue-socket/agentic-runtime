import requests as http_client
from flask import Flask, jsonify, request

app = Flask(__name__)

SHOP_CONFIRM_URL = "http://localhost:8000/payments/confirm"

account = {
    "id": "ACC-001",
    "holder": "John Doe",
    "balance": 50000.0,
    "transactions": [],
}


@app.route("/balance", methods=["GET"])
def get_balance():
    return jsonify({
        "status": "success",
        "account_id": account["id"],
        "holder": account["holder"],
        "balance": account["balance"],
    })


@app.route("/pay", methods=["POST"])
def make_payment():
    data = request.get_json()
    if not data:
        return jsonify({"status": "failed", "message": "Request body must be JSON"}), 400

    amount = data.get("amount")
    recipient = data.get("recipient")

    if amount is None or recipient is None:
        return jsonify({
            "status": "failed",
            "message": "Both 'amount' and 'recipient' fields are required",
        }), 400

    if not isinstance(amount, (int, float)) or amount <= 0:
        return jsonify({
            "status": "failed",
            "message": "Amount must be a positive number",
        }), 400

    if account["balance"] < amount:
        return jsonify({
            "status": "failed",
            "message": "Insufficient funds",
            "balance": account["balance"],
            "requested": amount,
        }), 402

    account["balance"] -= amount
    txn = {
        "recipient": recipient,
        "amount": amount,
        "balance_after": account["balance"],
    }
    account["transactions"].append(txn)

    return jsonify({
        "status": "success",
        "message": f"Payment of {amount} to {recipient} completed",
        "balance": account["balance"],
        "transaction": txn,
    })


@app.route("/pay/order", methods=["POST"])
def pay_order():
    data = request.get_json()
    if not data:
        return jsonify({"status": "failed", "message": "Request body must be JSON"}), 400

    order_id = data.get("order_id")
    amount = data.get("amount")

    if not order_id or amount is None:
        return jsonify({
            "status": "failed",
            "message": "Both 'order_id' and 'amount' fields are required",
        }), 400

    if not isinstance(amount, (int, float)) or amount <= 0:
        return jsonify({
            "status": "failed",
            "message": "Amount must be a positive number",
        }), 400

    if account["balance"] < amount:
        # Notify shop of failure
        try:
            http_client.post(SHOP_CONFIRM_URL, json={"order_id": order_id, "status": "failed"}, timeout=5)
        except http_client.RequestException:
            pass
        return jsonify({
            "status": "failed",
            "message": "Insufficient funds",
            "balance": account["balance"],
            "requested": amount,
        }), 402

    # Deduct balance
    account["balance"] -= amount
    txn = {
        "order_id": order_id,
        "amount": amount,
        "balance_after": account["balance"],
    }
    account["transactions"].append(txn)

    # Confirm payment to the shop
    try:
        shop_resp = http_client.post(SHOP_CONFIRM_URL, json={"order_id": order_id, "status": "success"}, timeout=5)
        shop_confirmed = shop_resp.ok
    except http_client.RequestException:
        shop_confirmed = False

    return jsonify({
        "status": "success",
        "message": f"Payment of {amount} for order {order_id} completed",
        "balance": account["balance"],
        "transaction": txn,
        "shop_notified": shop_confirmed,
    })


@app.route("/transactions", methods=["GET"])
def get_transactions():
    return jsonify({
        "status": "success",
        "account_id": account["id"],
        "transactions": account["transactions"],
    })


@app.route("/reset", methods=["POST"])
def reset_account():
    account["balance"] = 50000.0
    account["transactions"] = []
    return jsonify({
        "status": "success",
        "message": "Account reset to default balance",
        "balance": account["balance"],
    })


if __name__ == "__main__":
    app.run(debug=True, port=5000)

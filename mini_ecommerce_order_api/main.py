from enum import Enum

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel,Field,EmailStr
import os
from dotenv import load_dotenv
from supabase import create_client, Client
load_dotenv()

app=FastAPI()
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
SUPABASE_URL = os.getenv("SUPABASE_URL")
client = create_client(SUPABASE_URL,SUPABASE_KEY)

status = {"PLACED", "PROCESSING","SHIPPED", "DELIVERED"}

class Product(BaseModel):
    product_id :int= Field(gt=0)
    product_name:str
    product_quantity:int = Field(ge=0)
    product_cost_per_quantity:float

@app.post("/products")
def create_product(product:Product):
    product_exists = client.table("products").select("product_id").eq("product_id",product.product_id).execute()
    if product_exists.data:
        raise HTTPException(
            status_code=409,
            detail="product already exists please update its quantity"
        )
    response = client.table("products").insert(product.dict()).execute()
    return {
        "message": "new product is successfully added",
        "data":response.data
    }

@app.get("/products")
def get_products():
  response = client.table("products").select("*").execute()
  if not response.data:
      raise HTTPException(
          status_code=404,
          detail = "empty products"
      )   
  else :
      return response.data

class Customer(BaseModel):
    customer_id:int
    customer_name : str
    email :EmailStr
    phone_num:str

class Product_Status(str,Enum):
    PLACED ="PLACED"
    PROCESSING= "PROCESSING"
    SHIPPED = "SHIPPED"
    DELIVERED="DELIVERED"

class OrderItem(BaseModel):
    product_id: int = Field(gt=0)
    quantity: int = Field(gt=0)
     
class Orders(BaseModel):
    customer : Customer
    products: list[OrderItem] = Field(min_length=1)


@app.post("/orders")
def create_order(order: Orders):
    total_cost = 0
    order_items = []
    quantities_by_product = {}

    # Combine quantities when the same product appears more than once
    for item in order.products:
        quantities_by_product[item.product_id] = (
            quantities_by_product.get(item.product_id, 0)
            + item.quantity
        )

    # Validate products, check stock, and calculate the total
    for product_id, quantity in quantities_by_product.items():
        product_response = (
            client.table("products")
            .select("*")
            .eq("product_id", product_id)
            .execute()
        )

        if not product_response.data:
            raise HTTPException(
                status_code=404,
                detail=f"Product {product_id} not found"
            )

        product_details = product_response.data[0]

        if quantity > product_details["product_quantity"]:
            raise HTTPException(
                status_code=409,
                detail=f"Insufficient stock for product {product_id}"
            )

        unit_price = product_details["product_cost_per_quantity"]

        # Accumulate each product's subtotal
        total_cost += unit_price * quantity

        order_items.append({
            "product_id": product_id,
            "quantity": quantity,
            "unit_price": unit_price
        })

    # Create the order with server-calculated values
    order_data = {
        "customer_id": order.customer.customer_id,
        "total_amount": total_cost,
        "status": "PLACED"
    }

    order_response = (
        client.table("orders")
        .insert(order_data)
        .execute()
    )

    if not order_response.data:
        raise HTTPException(
            status_code=500,
            detail="Failed to create order"
        )

    order_id = order_response.data[0]["order_id"]

    # Insert the order items
    for item in order_items:
        item["order_id"] = order_id

    items_response = (
        client.table("order_items")
        .insert(order_items)
        .execute()
    )

    return {
        "message": "Order placed successfully",
        "order_id": order_id,
        "total_amount": total_cost,
        "status": "PLACED",
        "items": items_response.data
    }
@app.get("/orders")
def get_orders():
    response = client.table("orders").select("*").execute()
    return response.data

@app.get("/orders/{order_id}")
def get_order_detail(order_id: int):
    response = (
        client.table("orders")
        .select("""
            order_id,
            order_date,
            total_amount,
            status,
            customers(
                customer_id,
                customer_name,
                email,
                phone_num
            ),
            order_items(
                quantity,
                unit_price,
                products(
                    product_id,
                    product_name,
                    product_cost_per_quantity
                )
            )
        """)
        .eq("order_id", order_id)
        .execute()
    )

    if not response.data:
        raise HTTPException(
            status_code=404,
            detail="Order not found"
        )

    return response.data[0]

class UpdateOrderStatus(BaseModel):
    status: Product_Status

@app.put("/orders/{order_id}/status")
def update_order_status(order_id: int,order: UpdateOrderStatus):
    # Fetch the specific order
    order_response = (
        client.table("orders")
        .select("order_id, status")
        .eq("order_id", order_id)
        .execute()
    )

    if not order_response.data:
        raise HTTPException(
            status_code=404,
            detail="Order not found"
        )

    current_status = order_response.data[0]["status"]
    requested_status = order.status.value

    # Define valid status transitions
    next_status = {
        "PLACED": "PROCESSING",
        "PROCESSING": "SHIPPED",
        "SHIPPED": "DELIVERED"
    }

    if next_status.get(current_status) != requested_status:
        raise HTTPException(
            status_code=409,
            detail=(
                f"Invalid status transition from "
                f"{current_status} to {requested_status}"
            )
        )

    # Update only the status
    response = (
        client.table("orders")
        .update({"status": requested_status})
        .eq("order_id", order_id)
        .execute()
    )

    return {
        "message": "Order status updated successfully",
        "data": response.data
    }

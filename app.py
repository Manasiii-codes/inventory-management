"""Inventory management demo: MongoDB stores records; Neo4j mirrors the relationship graph."""
import os
from datetime import datetime, timezone
from bson import ObjectId
from dotenv import load_dotenv
from flask import Flask, jsonify, render_template, request
from pymongo import MongoClient, ASCENDING
from neo4j import GraphDatabase

load_dotenv()
app = Flask(__name__)

MONGO_URI = os.getenv("MONGO_URI", "mongodb://localhost:27017")
MONGO_DB = os.getenv("MONGO_DB", "inventory_management")
NEO4J_URI = os.getenv("NEO4J_URI", "bolt://localhost:7687")
NEO4J_USER = os.getenv("NEO4J_USER", "neo4j")
NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD", "Neo4jproject")

mongo_client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=2500)
db = mongo_client[MONGO_DB]
neo_driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD), connection_timeout=2)

# The sketch's exact hierarchy is retained in Neo4j:
# Inventory -> Category -> Supplier -> Product -> Quantity node.
DEFAULT_TREE = {
    "Electronics": ["Supplier 1", "Supplier 2"],
    "Stationery": ["Supplier 1", "Supplier 2"],
    "Furniture": ["Supplier 1", "Supplier 2"],
}


def json_doc(doc):
    if not doc:
        return doc
    result = dict(doc)
    result["id"] = str(result.pop("_id"))
    if isinstance(result.get("created_at"), datetime):
        result["created_at"] = result["created_at"].isoformat()
    return result


def neo_write_product(category, supplier, product, quantity, mongo_id):
    """Upsert the same category -> supplier -> product -> quantity shape in Neo4j."""
    with neo_driver.session() as session:
        session.run("""
            MERGE (i:Inventory {name: 'Inventory'})
            MERGE (c:Category {name: $category})
            MERGE (i)-[:HAS_CATEGORY]->(c)
            MERGE (s:Supplier {name: $supplier, category: $category})
            MERGE (c)-[:HAS_SUPPLIER]->(s)
            MERGE (p:Product {mongo_id: $mongo_id})
            SET p.name = $product, p.category = $category, p.supplier = $supplier
            MERGE (s)-[:SUPPLIES]->(p)
            MERGE (q:Quantity {product_id: $mongo_id})
            SET q.value = $quantity
            MERGE (p)-[:HAS_QUANTITY]->(q)
        """, category=category, supplier=supplier, product=product,
             quantity=quantity, mongo_id=mongo_id)


def mongo_ready():
    mongo_client.admin.command("ping")


def neo_ready():
    with neo_driver.session() as session:
        session.run("RETURN 1").single()


@app.get("/")
def home():
    return render_template("index.html")


@app.get("/api/health")
def health():
    status = {}
    for name, fn in (("mongodb", mongo_ready), ("neo4j", neo_ready)):
        try:
            fn()
            status[name] = "connected"
        except Exception as exc:
            status[name] = f"disconnected: {str(exc)[:140]}"
    return jsonify(status), (200 if all(v == "connected" for v in status.values()) else 503)


@app.get("/api/categories")
def categories():
    try:
        mongo_ready()
        names = sorted(set(db.products.distinct("category")) | set(DEFAULT_TREE.keys()))
        return jsonify(names)
    except Exception as exc:
        return jsonify({"error": f"MongoDB unavailable: {exc}"}), 503


@app.get("/api/suppliers")
def suppliers():
    category = request.args.get("category", "").strip()
    if not category:
        return jsonify({"error": "category query parameter is required"}), 400
    try:
        names = set(DEFAULT_TREE.get(category, []))
        names.update(db.products.distinct("supplier", {"category": category}))
        return jsonify(sorted(names))
    except Exception as exc:
        return jsonify({"error": f"Could not load suppliers: {exc}"}), 503


@app.get("/api/products")
def list_products():
    try:
        query = {}
        for key in ("category", "supplier"):
            value = request.args.get(key, "").strip()
            if value:
                query[key] = value
        docs = [json_doc(d) for d in db.products.find(query).sort("created_at", -1)]
        return jsonify(docs)
    except Exception as exc:
        return jsonify({"error": f"Could not load products: {exc}"}), 503


@app.post("/api/products")
def create_product():
    payload = request.get_json(silent=True) or {}
    category = str(payload.get("category", "")).strip()
    supplier = str(payload.get("supplier", "")).strip()
    product = str(payload.get("product", "")).strip()
    try:
        quantity = int(payload.get("quantity", -1))
    except (ValueError, TypeError):
        quantity = -1
    if not all((category, supplier, product)):
        return jsonify({"error": "Category, supplier, and product are required."}), 400
    if quantity < 0:
        return jsonify({"error": "Quantity must be a whole number of 0 or more."}), 400

    now = datetime.now(timezone.utc)
    doc = {"category": category, "supplier": supplier, "product": product,
           "quantity": quantity, "created_at": now}
    try:
        mongo_ready()
        inserted = db.products.insert_one(doc)
        mongo_id = str(inserted.inserted_id)
    except Exception as exc:
        return jsonify({"error": f"MongoDB insert failed: {exc}"}), 503

    graph_synced = True
    graph_error = None
    try:
        neo_write_product(category, supplier, product, quantity, mongo_id)
    except Exception as exc:
        graph_synced = False
        graph_error = str(exc)
    response = json_doc({**doc, "_id": inserted.inserted_id})
    response["neo4j_synced"] = graph_synced
    if graph_error:
        response["neo4j_warning"] = "Saved in MongoDB, but Neo4j sync failed. Check the Neo4j connection."
    return jsonify(response), 201


@app.put("/api/products/<product_id>")
def update_product(product_id):
    payload = request.get_json(silent=True) or {}
    updates = {}
    for key in ("category", "supplier", "product"):
        if key in payload:
            value = str(payload[key]).strip()
            if not value:
                return jsonify({"error": f"{key} cannot be empty."}), 400
            updates[key] = value
    if "quantity" in payload:
        try:
            updates["quantity"] = int(payload["quantity"])
        except (ValueError, TypeError):
            return jsonify({"error": "Quantity must be a whole number."}), 400
        if updates["quantity"] < 0:
            return jsonify({"error": "Quantity cannot be negative."}), 400
    if not updates:
        return jsonify({"error": "No updates provided."}), 400
    try:
        oid = ObjectId(product_id)
        old = db.products.find_one({"_id": oid})
        if not old:
            return jsonify({"error": "Product not found."}), 404
        db.products.update_one({"_id": oid}, {"$set": updates})
        fresh = db.products.find_one({"_id": oid})
        try:
            # Keep graph identifiers stable while updating the product's relationships/properties.
            with neo_driver.session() as session:
                session.run("MATCH (p:Product {mongo_id: $id}) DETACH DELETE p", id=product_id)
            neo_write_product(fresh["category"], fresh["supplier"], fresh["product"], fresh["quantity"], product_id)
            graph_synced = True
        except Exception:
            graph_synced = False
        result = json_doc(fresh)
        result["neo4j_synced"] = graph_synced
        return jsonify(result)
    except Exception as exc:
        return jsonify({"error": f"Could not update product: {exc}"}), 503


@app.delete("/api/products/<product_id>")
def delete_product(product_id):
    try:
        oid = ObjectId(product_id)
        result = db.products.delete_one({"_id": oid})
        if not result.deleted_count:
            return jsonify({"error": "Product not found."}), 404
        try:
            with neo_driver.session() as session:
                session.run("MATCH (p:Product {mongo_id: $id}) DETACH DELETE p", id=product_id)
                session.run("MATCH (q:Quantity {product_id: $id}) DETACH DELETE q", id=product_id)
            graph_synced = True
        except Exception:
            graph_synced = False
        return jsonify({"deleted": True, "neo4j_synced": graph_synced})
    except Exception as exc:
        return jsonify({"error": f"Could not delete product: {exc}"}), 503


@app.get("/api/graph")
def graph_data():
    """Return graph nodes and edges for the browser visualization."""
    try:
        with neo_driver.session() as session:
            records = session.run("""
                MATCH (i:Inventory {name:'Inventory'})-[:HAS_CATEGORY]->(c:Category)
                OPTIONAL MATCH (c)-[:HAS_SUPPLIER]->(s:Supplier)
                OPTIONAL MATCH (s)-[:SUPPLIES]->(p:Product)
                OPTIONAL MATCH (p)-[:HAS_QUANTITY]->(q:Quantity)
                RETURN i.name AS inventory, c.name AS category, s.name AS supplier,
                       s.category AS supplier_category, p.mongo_id AS mongo_id,
                       p.name AS product, q.value AS quantity
                ORDER BY category, supplier, product
            """).data()
        nodes, edges, seen = [], [], set()
        def add_node(node_id, label, kind, properties=None):
            if node_id not in seen:
                seen.add(node_id)
                nodes.append({"id": node_id, "label": label, "kind": kind, "properties": properties or {}})
        add_node("inventory", "Inventory", "Inventory")
        for r in records:
            if not r["category"]:
                continue
            cid = "category:" + r["category"]
            add_node(cid, r["category"], "Category")
            edges.append({"from": "inventory", "to": cid, "label": "HAS_CATEGORY"})
            if r["supplier"]:
                sid = "supplier:" + str(r["supplier_category"] or r["category"]) + ":" + r["supplier"]
                add_node(sid, r["supplier"], "Supplier", {"category": r["category"]})
                edges.append({"from": cid, "to": sid, "label": "HAS_SUPPLIER"})
                if r["mongo_id"]:
                    pid = "product:" + r["mongo_id"]
                    add_node(pid, r["product"], "Product", {"mongo_id": r["mongo_id"]})
                    edges.append({"from": sid, "to": pid, "label": "SUPPLIES"})
                    qid = "quantity:" + r["mongo_id"]
                    add_node(qid, str(r["quantity"]), "Quantity", {"value": r["quantity"]})
                    edges.append({"from": pid, "to": qid, "label": "HAS_QUANTITY"})
        return jsonify({"nodes": nodes, "edges": edges})
    except Exception as exc:
        return jsonify({"error": f"Neo4j graph unavailable: {exc}"}), 503


@app.post("/api/seed")
def seed():
    """Insert illustrative starter records in MongoDB and mirror them in Neo4j."""
    examples = [
        ("Electronics", "Supplier 1", "Wireless Mouse", 25),
        ("Electronics", "Supplier 2", "USB-C Cable", 60),
        ("Stationery", "Supplier 1", "A4 Notebook", 100),
        ("Stationery", "Supplier 2", "Blue Ball Pen", 250),
        ("Furniture", "Supplier 1", "Office Chair", 12),
        ("Furniture", "Supplier 2", "Study Desk", 8),
    ]
    inserted_count, graph_count = 0, 0
    try:
        for category, supplier, product, quantity in examples:
            if db.products.find_one({"category": category, "supplier": supplier, "product": product}):
                continue
            doc = {"category": category, "supplier": supplier, "product": product,
                   "quantity": quantity, "created_at": datetime.now(timezone.utc)}
            result = db.products.insert_one(doc)
            inserted_count += 1
            try:
                neo_write_product(category, supplier, product, quantity, str(result.inserted_id))
                graph_count += 1
            except Exception:
                pass
        # Ensure all three category branches exist even before products are added.
        with neo_driver.session() as session:
            session.run("MERGE (i:Inventory {name:'Inventory'})")
            for category, suppliers_for_category in DEFAULT_TREE.items():
                session.run("""
                    MATCH (i:Inventory {name:'Inventory'})
                    MERGE (c:Category {name:$category})
                    MERGE (i)-[:HAS_CATEGORY]->(c)
                """, category=category)
                for supplier in suppliers_for_category:
                    session.run("""
                        MATCH (c:Category {name:$category})
                        MERGE (s:Supplier {name:$supplier, category:$category})
                        MERGE (c)-[:HAS_SUPPLIER]->(s)
                    """, category=category, supplier=supplier)
        return jsonify({"inserted": inserted_count, "graph_synced": graph_count,
                        "message": "Starter data checked/inserted."})
    except Exception as exc:
        return jsonify({"error": f"Seeding failed: {exc}. Check both database connections."}), 503


@app.get("/api/neo4j-browser")
def neo4j_browser_hint():
    return jsonify({"query": "MATCH (i:Inventory)-[r]->(n) RETURN i,r,n LIMIT 100",
                    "note": "Run this query in Neo4j Browser to inspect the relationship graph."})

if __name__ == "__main__":
    app.run(debug=True, port=int(os.getenv("PORT", "5000")))

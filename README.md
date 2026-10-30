# Stockroom — Inventory Management System

A small full-stack inventory management project using **HTML, CSS, JavaScript, Python/Flask, MongoDB, and Neo4j**. It follows the relationship pattern in your hand-drawn diagram:

```text
Inventory
├── Category: Electronics
│   ├── Supplier 1 → Product → Quantity
│   └── Supplier 2 → Product → Quantity
├── Category: Stationery
│   ├── Supplier 1 → Product → Quantity
│   └── Supplier 2 → Product → Quantity
└── Category: Furniture
    ├── Supplier 1 → Product → Quantity
    └── Supplier 2 → Product → Quantity
```

**MongoDB** is the source of truth for product records (`products` collection). **Neo4j** mirrors the same hierarchy as graph nodes and relationships. Quantity is deliberately represented as a separate `Quantity` node, matching the diagram rather than storing it only as a product property.

## Features

- Overview cards: product count, total units, categories and supplier branches.
- Add, edit, delete, search and filter inventory records.
- Categories: Electronics, Stationery, Furniture; two supplier branches per category.
- Browser relationship graph with zoom, pan and clickable nodes.
- “Load sample data” creates six example products and ensures all category/supplier branches exist in Neo4j.
- Health endpoint checks MongoDB and Neo4j connections.

## 1. Requirements

- Python 3.10+
- MongoDB running locally or a MongoDB connection string
- Neo4j 5.x running locally or a Neo4j connection URI, with Bolt enabled

## 2. Configure databases

### MongoDB

Start your MongoDB server. The default URI is `mongodb://localhost:27017` and database name is `inventory_management`.

### Neo4j

Create/start a Neo4j database in Neo4j Desktop or your Neo4j server. Enable Bolt and note its URI, username and password. The common local Bolt URI is `bolt://localhost:7687`.

Copy `.env.example` to `.env`, then set your real Neo4j password and any custom connection values:

```bash
cp .env.example .env
```

Do not commit or share your `.env` file.

## 3. Install and run

From this project folder:

**Windows (PowerShell)**

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env
# Edit .env and set NEO4J_PASSWORD
python app.py
```

**macOS / Linux**

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# Edit .env and set NEO4J_PASSWORD
python app.py
```

Open `http://127.0.0.1:5000` in your browser. Click **Load sample data** to add example records. Both databases must be running and credentials correct for the full experience.

> The frontend loads the vis-network visualization library from a CDN, so internet access is needed for that graph library unless you vendor it locally.

## 4. Verify in Neo4j Browser

Run this Cypher query to view the exact hierarchy:

```cypher
MATCH (i:Inventory)-[r1:HAS_CATEGORY]->(c:Category)
OPTIONAL MATCH (c)-[r2:HAS_SUPPLIER]->(s:Supplier)
OPTIONAL MATCH (s)-[r3:SUPPLIES]->(p:Product)
OPTIONAL MATCH (p)-[r4:HAS_QUANTITY]->(q:Quantity)
RETURN i, r1, c, r2, s, r3, p, r4, q
```

Useful shorter query:

```cypher
MATCH (n)-[r]->(m) RETURN n, r, m LIMIT 100
```

## 5. MongoDB structure

Database: `inventory_management`  
Collection: `products`

Example document:

```json
{
  "category": "Electronics",
  "supplier": "Supplier 1",
  "product": "Wireless Mouse",
  "quantity": 25,
  "created_at": "ISODate(...)"
}
```

MongoDB uses a normal document with `quantity` as a number; Neo4j mirrors it as a separate `(:Quantity {value: 25})` node to preserve your diagram's graph structure.

## 6. API endpoints

| Method | Endpoint | Purpose |
|---|---|---|
| GET | `/api/health` | Check both database connections |
| GET | `/api/categories` | List categories |
| GET | `/api/suppliers?category=Electronics` | List suppliers for a category |
| GET | `/api/products` | List inventory; optional `category` and `supplier` filters |
| POST | `/api/products` | Insert product in MongoDB and mirror to Neo4j |
| PUT | `/api/products/<id>` | Update product and refresh graph node |
| DELETE | `/api/products/<id>` | Delete product from both databases where reachable |
| GET | `/api/graph` | Return graph nodes/edges for frontend visualization |
| POST | `/api/seed` | Insert sample records and ensure all category/supplier branches |

## Notes

- MongoDB and Neo4j are separate services; this demo syncs them in the Flask request rather than using a distributed transaction. If Neo4j is unavailable during an insert, the record is retained in MongoDB and the API response warns that graph sync failed.
- For production, add authentication, authorization, CSRF protection, server-side logging, database indexes, stronger validation, and a retry/reconciliation job for failed graph syncs. Do not expose database ports publicly without appropriate security.

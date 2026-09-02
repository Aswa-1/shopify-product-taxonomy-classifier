# Shopify Product Taxonomy Automated Classifier (Production Prototype)

A scalable, resilient Django & REST Framework web application designed for automated classification of product catalogues into official English Shopify Product Taxonomy categories, with category attribute extraction, transparent confidence scoring, alternative category suggestions, and manual review routing.

---

## 🌟 Architecture Overview

```
                        ┌────────────────────────────────────────┐
                        │        Bootstrap 5 Web UI /           │
                        │       Django REST API Framework       │
                        └───────────────────┬────────────────────┘
                                            │
                        ┌───────────────────▼────────────────────┐
                        │        Django ORM Data Models         │
                        │  (Product, Image, Classification, Job) │
                        └───────────────────┬────────────────────┘
                                            │
                        ┌───────────────────▼────────────────────┐
                        │      Celery Worker + Redis Queue       │
                        │    (Fallback: ThreadPool Background)   │
                        └───────────────────┬────────────────────┘
                                            │
                        ┌───────────────────▼────────────────────┐
                        │     Hybrid Classification Engine       │
                        │ ┌────────────────────────────────────┐ │
                        │ │ 1. Data Normalizer (HTML/_x000D_)  │ │
                        │ │ 2. TF-IDF Candidate Retrieval      │ │
                        │ │ 3. Multi-Signal Scoring Engine     │ │
                        │ │ 4. Safe Image Downloader & Inspector│ │
                        │ │ 5. Attribute Extraction & Scoring  │ │
                        │ └────────────────────────────────────┘ │
                        └───────────────────┬────────────────────┘
                                            │
                        ┌───────────────────▼────────────────────┐
                        │    Official Shopify Product Taxonomy   │
                        │   (14,606 Categories & 8,240 Attrs)   │
                        └────────────────────────────────────────┘
```

---

## 🚀 Main Features

1. **Official Shopify Taxonomy Integration**:
   - Downloads and indexes official Shopify taxonomy from GitHub (`categories.txt`, `attributes.txt`, `taxonomy.json`).
   - Hierarchical parent-child tree mapping across 14,606 categories and 8,240 attributes.

2. **Resilient Data Processing**:
   - Parses complex 48-column Excel catalogues (`Product List.xlsx`).
   - Handles missing descriptions, missing images, broken/inaccessible image URLs, dirty HTML, and Excel whitespace (`_x000D_`) without stopping batch processing.
   - Computes MD5 content hashes for variant deduplication.

3. **Hybrid Classification & Demo Mode**:
   - **Offline / Demo Mode**: Runs out-of-the-box without external AI API keys using token overlap, hierarchy matching, and TF-IDF sparse vector candidate retrieval.
   - **Enhanced AI Mode**: Accepts optional `AI_API_KEY` for LLM vision and text classification.

4. **Transparent Confidence Scoring & Manual Review Queue**:
   - Multi-signal scoring equation combining lexical similarity, hierarchy alignment, title match, evidence completeness, and image signals ($0.00$ to $1.00$).
   - High ($\ge 0.80$), Medium ($0.60 - 0.79$), Low / Manual Review ($< 0.60$).
   - Flagged low-confidence products receive Top 3 ranked alternative categories with confidence scores and explanations.

5. **Resumable Asynchronous Batching**:
   - Job tracking with persistent product statuses (`PENDING`, `PROCESSING`, `COMPLETED`, `FAILED`, `RETRY`, `MANUAL_REVIEW`).
   - Chunked batch processing via Celery & Redis (with automatic fallback to background threads if Redis is offline).
   - Resumable: Restarting a job processes only pending and failed products without duplicate execution.

---

## 🛠️ Quick Start & Installation

### 1. Prerequisites
- Python 3.11+
- Virtualenv
- Optional: Redis Server & Celery (for production worker processing)
- Optional: MariaDB / MySQL Server (for preferred database)

### 2. Environment Setup
```bash
git clone <repository_url>
cd product
python -m venv venv
# On Windows:
venv\Scripts\activate
# On Linux/macOS:
source venv/bin/activate

pip install -r requirements.txt
```

### 3. Environment Variables Configuration
Copy `.env.example` to `.env`:
```bash
cp .env.example .env
```
Key configuration parameters:
- `DB_ENGINE`: Database engine (`django.db.backends.sqlite3` for default local fallback or `django.db.backends.mysql` for MariaDB).
- `DATABASE_URL`: MariaDB connection URL e.g. `mysql://user:password@localhost:3306/shopify_classifier`.
- `REDIS_URL`: Redis URL e.g. `redis://127.0.0.1:6379/0`.
- `AI_API_KEY`: Optional external LLM API key.

---

## 🗄️ Database Setup

### MariaDB Setup (Preferred Production Database)
1. Create a database in MariaDB:
   ```sql
   CREATE DATABASE shopify_classifier CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
   ```
2. Set environment variables in `.env`:
   ```ini
   DATABASE_URL=mysql://root:password@localhost:3306/shopify_classifier
   ```
3. Run Django migrations:
   ```bash
   python manage.py makemigrations taxonomy products
   python manage.py migrate
   ```

### SQLite Setup (Zero-Configuration Local Fallback)
Default out of the box. Simply run:
```bash
python manage.py makemigrations taxonomy products
python manage.py migrate
```

---

## 🏷️ Import Official Shopify Taxonomy

To populate the database with all 14,606 official Shopify Product Taxonomy categories and 8,240 attributes directly from GitHub:
```bash
python manage.py import_shopify_taxonomy
```

---

## ⚡ Running Background Processing (Celery & Redis)

### Production Mode (Celery + Redis)
1. Start Redis Server.
2. In a separate terminal, launch Celery worker:
   ```bash
   celery -A shopify_classifier worker --loglevel=info --concurrency=4
   ```

### Development Fallback Mode
If Redis is not running, the application automatically catches broker connection failures and delegates batch jobs to background `ThreadPoolExecutor` threads so execution completes seamlessly without stopping!

---

## 💻 Running the Web Application

Launch the Django development server:
```bash
python manage.py runserver 8000
```
Open your browser at [http://127.0.0.1:8000/](http://127.0.0.1:8000/).

---

## 🐳 Docker Deployment

To launch the complete stack (MariaDB + Redis + Django Web + Celery Worker) using Docker Compose:
```bash
docker-compose up --build
```

---

## 📡 REST API Documentation

| Endpoint | Method | Description |
| :--- | :--- | :--- |
| `POST /api/import/` | `POST` | Upload Excel file (`.xlsx`), create `ProcessingJob`, trigger batch classification. |
| `GET /api/products/` | `GET` | Paginated product list. Supports `?q=`, `?status=`, `?requires_review=true`, `?confidence_lt=0.60`. |
| `GET /api/products/{id}/` | `GET` | Retrieve single product details with image status & classification. |
| `GET /api/products/{id}/classification/` | `GET` | Retrieve classification result, top alternatives, and extracted attributes. |
| `POST /api/products/{id}/approve/` | `POST` | Approve classification result. |
| `POST /api/products/{id}/reclassify/` | `POST` | Trigger instant re-classification for product. |
| `PATCH /api/products/{id}/update_classification/` | `PATCH` | Manually override selected category or attributes. |
| `GET /api/jobs/` | `GET` | List all background processing jobs. |
| `GET /api/jobs/{id}/` | `GET` | Retrieve job progress percentages and counts. |
| `POST /api/jobs/{id}/resume/` | `POST` | Resume processing pending/failed products in a job. |
| `GET /api/taxonomy/` | `GET` | Search and list Shopify taxonomy categories (`?q=sofa`). |

---

## 🧪 Running Automated Tests

Run the automated Django test suite:
```bash
python manage.py test products.tests
```

Or using `pytest`:
```bash
python -m pytest
```

---

## ⚠️ Known Limitations & Future Enhancements

1. **LLM API Concurrency Rate Limits**: When operating with external AI vision API keys on large catalogues (10,000+ products), concurrency should be configured via `MAX_CONCURRENT_REQUESTS` in `.env` to prevent HTTP 429 rate limit errors from API providers.
2. **Local Image Storage**: Currently product images are downloaded and validated in memory. In a multi-server setup, configuring Amazon S3 or Google Cloud Storage as Django's `DEFAULT_FILE_STORAGE` is recommended for persistent image thumbnail storage.

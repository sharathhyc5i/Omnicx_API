# OmniCX Dashboard - Standalone Companion Python Backend

This folder contains the isolated Python FastAPI backend for the OmniCX Dashboard. It uses `pyodbc` to connect to **Microsoft SQL Server** via Active Directory Integrated Authentication, and exposes the reporting periods in the `[dbo].[CXReport_DisplayName_MetricPercents]` table.

---

## Technical Features

1. **FastAPI Framework**: Blazing fast, self-documenting routing with typed validation in Pydantic.
2. **Auto-Proactive Table Alignment**: If your MS SQL Server `DISPLAY` table is missing action tracking columns (`added_by_user`, `added_date`, `updated_by_user`, `updated_date`), the backend will automatically execute a silent `ALTER TABLE` to ensure zero runtime schema mismatches.
3. **CORS Fully Enabled**: Set to allow standard dashboard client proxying.

---

## Local Development Prerequisites

### 1. Install System ODBC Driver
Make sure you have the official Microsoft ODBC client installed in your OS environment:
- **Windows**: Microsoft ODBC Driver 18 for SQL Server (often pre-installed or part of SSMS).
- **macOS / Linux**: Use Homebrew to install MS ODBC drivers:
  ```bash
  # macOS
  brew tap microsoft/mssql-release https://github.com/microsoft/homebrew-mssql-release
  brew update
  HOMEBREW_ACCEPT_EULA=Y brew install mssql-tools18 unixodbc

  # Ubuntu/Debian
  sudo apt-get install -y unixodbc-dev
  ```

---

## Local Startup Instructions

### 1. Setup Virtual Environment
Run the following inside this `/backend` folder:
```bash
# Create virtual environment
python -m venv venv

# Activate virtual environment
# On macOS/Linux:
source venv/bin/activate
# On Windows Command Prompt:
venv\Scripts\activate
# On Windows PowerShell:
.\venv\Scripts\Activate.ps1
```

### 2. Install Packages
```bash
pip install -r requirements.txt
```

### 3. Configure Connection String
You can set an environment variable to override the default connection credentials:
```bash
# Unix (Sh / Bash)
export SQL_SERVER_CONN_STR="Driver={ODBC Driver 18 for SQL Server};Server=YOUR_SERVER;Database=YOUR_DB;Authentication=ActiveDirectoryIntegrated;Encrypt=yes;TrustServerCertificate=yes;"

# Windows (Command Prompt)
set SQL_SERVER_CONN_STR="Driver={ODBC Driver 18 for SQL Server};Server=YOUR_SERVER;Database=YOUR_DB;Authentication=ActiveDirectoryIntegrated;Encrypt=yes;TrustServerCertificate=yes;"

# Windows (PowerShell)
$env:SQL_SERVER_CONN_STR="Driver={ODBC Driver 18 for SQL Server};Server=YOUR_SERVER;Database=YOUR_DB;Authentication=ActiveDirectoryIntegrated;Encrypt=yes;TrustServerCertificate=yes;"
```

### 4. Open the Backend Server
```bash
uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```
Once active, you can preview the interactive Swagger API docs documentation by visiting:
* **http://localhost:8000/docs**

---

## Standalone Container Deployment (Dockerfile Pattern)

If you are deploying this backend on platforms like **Azure Container Apps**, **AWS ECS**, or **Google Cloud Run**, you can build it using a Linux container base that includes SQL Server drivers. Below is a sample `Dockerfile`:

```dockerfile
# Use official Debian-based Python image (since we need msodbcsql18 Debian packages)
FROM python:3.10-slim

# Install system dependencies & Microsoft ODBC packages
RUN apt-get update && apt-get install -y curl gnupg2 && \
    curl https://packages.microsoft.com/keys/microsoft.asc | apt-key add - && \
    curl https://packages.microsoft.com/config/debian/11/prod.list > /etc/apt/sources.list.d/mssql-release.list && \
    apt-get update && \
    ACCEPT_EULA=Y apt-get install -y msodbcsql18 unixodbc-dev g++ && \
    apt-get clean && rm -rf /var/lib/apt/lists/*

# Establish working dir
WORKDIR /app

# Install packages
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy source code
COPY main.py .

# Expose FastAPI listening port
EXPOSE 8000

# Execute server
CMD ["uvicorn", "main:app", "---host", "0.0.0.0", "--port", "8000"]
```

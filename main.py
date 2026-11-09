import os
import pyodbc
import psycopg2
import psycopg2.extras


from datetime import datetime, timezone
from typing import List, Optional
from pydantic import BaseModel, Field
from fastapi import FastAPI, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware


# ---------------------------------------------------------
# FastAPI Application
# ---------------------------------------------------------

app = FastAPI(
    title="OmniCX Python ODBC Companion Backend",
    description=(
        "Read-only API exposing SQL Server "
        "[dbo].[CXReport_DisplayName_MetricPercents_KEEP06232026] "
        "records to the React Frontend Dashboard, plus a "
        "PostgreSQL-backed user login audit API."
    ),
    version="1.1.0"
)


# ---------------------------------------------------------
# CORS
# ---------------------------------------------------------

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Restrict this in production
    allow_credentials=True,
    allow_methods=["GET", "POST"],  # POST added for /api/user-login
    allow_headers=["*"],
)


# ---------------------------------------------------------
# SQL Server Connection (existing, read-only)
# ---------------------------------------------------------

DEFAULT_CONN_STR = (
    "Driver={ODBC Driver 18 for SQL Server};"
    "Server=AZPWRSSQL003;"
    "Database=WWRCM_PowerBI;"
    "Authentication=ActiveDirectoryIntegrated;"
    "Encrypt=yes;"
    "TrustServerCertificate=yes;"
)


def get_db_connection():
    """
    Creates a read-only SQL Server connection.
    The connection string can be supplied through the
    SQL_SERVER_CONN_STR environment variable.
    """
    conn_str = os.getenv("SQL_SERVER_CONN_STR", DEFAULT_CONN_STR)

    try:
        return pyodbc.connect(conn_str)
    except Exception as e:
        print(f"[DB ERROR] ODBC Connection to SQL Server failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Database connection failed: {str(e)}"
        )


# ---------------------------------------------------------
# PostgreSQL Connection (user login audit)
# ---------------------------------------------------------
# Never hard-code the password. Set it in the environment:
#   Windows (PowerShell):  $env:PG_PASSWORD="your_password"
#   Linux/macOS:           export PG_PASSWORD="your_password"

PG_CONFIG = {
    "user": os.getenv("PG_USER", "omnicx_admin"),
    "password": os.getenv("PG_PASSWORD"),
    "host": os.getenv("PG_HOST", "omnicx.postgres.database.azure.com"),
    "port": int(os.getenv("PG_PORT", "5432")),
    "database": os.getenv("PG_DATABASE", "postgres"),
    "sslmode": os.getenv("PG_SSLMODE", "require"),  # Azure requires SSL
}


def get_pg_connection():
    if not PG_CONFIG["password"]:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="PG_PASSWORD environment variable is not set."
        )

    try:
        return psycopg2.connect(**PG_CONFIG)
    except Exception as e:
        print(f"[PG ERROR] Connection to PostgreSQL failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"PostgreSQL connection failed: {str(e)}"
        )


CREATE_USER_LOGIN_TABLE = """
    CREATE TABLE IF NOT EXISTS public.user_login_details (
        id                    BIGSERIAL PRIMARY KEY,
        user_id               VARCHAR(100)  NOT NULL,
        user_name             VARCHAR(255)  NOT NULL,
        user_email            VARCHAR(255)  NOT NULL,
        login_datetime_start  TIMESTAMPTZ   NOT NULL DEFAULT NOW(),
        login_datetime_end    TIMESTAMPTZ   NULL,
        user_role             VARCHAR(50)   NOT NULL DEFAULT 'admin',
        created_at            TIMESTAMPTZ   NOT NULL DEFAULT NOW()
    );

    CREATE INDEX IF NOT EXISTS idx_user_login_details_user_id
        ON public.user_login_details (user_id);
"""


@app.on_event("startup")
def ensure_user_login_table():
    """Creates the login table on startup if it doesn't exist."""
    if not PG_CONFIG["password"]:
        print("[PG WARN] PG_PASSWORD not set; skipping table check.")
        return

    try:
        conn = psycopg2.connect(**PG_CONFIG)
        with conn, conn.cursor() as cur:
            cur.execute(CREATE_USER_LOGIN_TABLE)
        conn.close()
        print("[PG] user_login_details table is ready.")
    except Exception as e:
        print(f"[PG WARN] Could not verify user_login_details table: {e}")


# ---------------------------------------------------------
# Response / Request Models
# ---------------------------------------------------------

class DisplayItem(BaseModel):
    partner_display_name: str
    month_end: str

    sales_hours_compliance_percent: float = 0.0
    pa_hours_compliance_percent: float = 0.0
    mm_hours_compliance_percent: float = 0.0

    win_essentials_completion_percent: float = 0.0

    mshop_ee_points_percent: float = 0.0
    mshop_ba_points_percent: float = 0.0

    wots_submission_percent: float = 0.0
    wots_quality_submission_percent: float = 0.0
    wots_windows_positive_sentiment_percent: float = 0.0


class UserLoginCreate(BaseModel):
    user_id: str = Field(..., min_length=1, max_length=100)
    user_name: str = Field(..., min_length=1, max_length=255)
    user_email: str = Field(
        ...,
        min_length=3,
        max_length=255,
        pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$"
    )
    login_datetime_start: Optional[datetime] = None  # defaults to now (UTC)
    login_datetime_end: Optional[datetime] = None
    user_role: str = Field(default="admin", max_length=50)


class UserLoginResponse(BaseModel):
    id: int
    user_id: str
    user_name: str
    user_email: str
    login_datetime_start: datetime
    login_datetime_end: Optional[datetime] = None
    user_role: str
    created_at: datetime


# ---------------------------------------------------------
# Health Check
# ---------------------------------------------------------

@app.get("/api/health")
def health_check():
    return {"status": "online"}


# ---------------------------------------------------------
# GET DISPLAY RECORDS (SQL Server)
# ---------------------------------------------------------

@app.get("/api/display", response_model=List[DisplayItem])
def get_all_records():

    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        select_query = """
            SELECT
                partner_display_name,
                month_end,
                sales_hours_compliance_percent,
                pa_hours_compliance_percent,
                mm_hours_compliance_percent,
                win_essentials_completion_percent,
                mshop_ee_points_percent,
                mshop_ba_points_percent,
                wots_submission_percent,
                wots_quality_submission_percent,
                wots_windows_positive_sentiment_percent
            FROM [WWRCM_PowerBI].[dbo].[CXReport_DisplayName_MetricPercents]
        """

        cursor.execute(select_query)
        columns = [column[0] for column in cursor.description]
        rows = cursor.fetchall()

        metric_fields = [
            "sales_hours_compliance_percent",
            "pa_hours_compliance_percent",
            "mm_hours_compliance_percent",
            "win_essentials_completion_percent",
            "mshop_ee_points_percent",
            "mshop_ba_points_percent",
            "wots_submission_percent",
            "wots_quality_submission_percent",
            "wots_windows_positive_sentiment_percent",
        ]

        results = []
        for row in rows:
            row_dict = dict(zip(columns, row))
            month_end = row_dict.get("month_end")

            results.append(
                DisplayItem(
                    partner_display_name=row_dict.get("partner_display_name") or "",
                    month_end=str(month_end) if month_end is not None else "",
                    **{f: float(row_dict.get(f) or 0.0) for f in metric_fields}
                )
            )

        return results

    except Exception as e:
        print(f"[GET FAILED] Error querying DISPLAY table: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Database query error: {str(e)}"
        )

    finally:
        cursor.close()
        conn.close()


# ---------------------------------------------------------
# POST USER LOGIN DETAILS (PostgreSQL)
# ---------------------------------------------------------

@app.post(
    "/api/user-login",
    response_model=UserLoginResponse,
    status_code=status.HTTP_201_CREATED
)
def create_user_login(payload: UserLoginCreate):
    """
    Saves a user login record.
    - login_datetime_start defaults to the current UTC time.
    - user_role defaults to 'admin'.
    """

    login_start = payload.login_datetime_start or datetime.now(timezone.utc)

    if payload.login_datetime_end and payload.login_datetime_end < login_start:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="login_datetime_end cannot be earlier than login_datetime_start."
        )

    insert_query = """
        INSERT INTO public.user_login_details (
            user_id,
            user_name,
            user_email,
            login_datetime_start,
            login_datetime_end,
            user_role
        )
        VALUES (%s, %s, %s, %s, %s, %s)
        RETURNING
            id, user_id, user_name, user_email,
            login_datetime_start, login_datetime_end,
            user_role, created_at;
    """

    conn = get_pg_connection()

    try:
        with conn:  # commits on success, rolls back on error
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(
                    insert_query,
                    (
                        payload.user_id,
                        payload.user_name,
                        payload.user_email.lower(),
                        login_start,
                        payload.login_datetime_end,
                        payload.user_role or "admin",
                    )
                )
                row = cur.fetchone()

        return UserLoginResponse(**row)

    except Exception as e:
        print(f"[POST FAILED] Error inserting user login: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Database insert error: {str(e)}"
        )

    finally:
        conn.close()

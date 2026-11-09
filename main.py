import os
import pyodbc
import psycopg2
import psycopg2.extras

from datetime import datetime, timezone
from typing import List, Optional
from pydantic import BaseModel, Field
from fastapi import FastAPI, HTTPException, Query, Response, status
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
    allow_methods=["GET", "POST", "DELETE"],
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
    "connect_timeout": int(os.getenv("PG_CONNECT_TIMEOUT", "10")),  # never hang startup
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

    -- Running totals (added safely to an existing table too)
    ALTER TABLE public.user_login_details
        ADD COLUMN IF NOT EXISTS total_time_spent_mins NUMERIC(14, 2) NOT NULL DEFAULT 0;
    ALTER TABLE public.user_login_details
        ADD COLUMN IF NOT EXISTS total_time_spent_hrs  NUMERIC(12, 2) NOT NULL DEFAULT 0;
    ALTER TABLE public.user_login_details
        ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW();
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
    total_time_spent_mins: float = 0.0
    total_time_spent_hrs: float = 0.0
    created_at: datetime
    updated_at: Optional[datetime] = None


USER_LOGIN_COLUMNS = """
    id, user_id, user_name, user_email,
    login_datetime_start, login_datetime_end,
    user_role, total_time_spent_mins, total_time_spent_hrs,
    created_at, updated_at
"""


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
def create_or_update_user_login(payload: UserLoginCreate, response: Response):
    """
    Saves a user's login session.

    - New user_id: inserts a row (returns 201).
    - Existing user_id: updates that user's row (returns 200) with the
      latest session times, name, email and role.
    - Session time (login_datetime_end - login_datetime_start) is added to
      total_time_spent_mins / total_time_spent_hrs. A session without
      login_datetime_end adds 0 (e.g. the call made at login time).
    - login_datetime_start defaults to now (UTC); user_role defaults to 'admin'.
    """

    login_start = payload.login_datetime_start or datetime.now(timezone.utc)
    login_end = payload.login_datetime_end

    # Treat timestamps without a timezone as UTC so they can be compared.
    if login_start.tzinfo is None:
        login_start = login_start.replace(tzinfo=timezone.utc)
    if login_end is not None and login_end.tzinfo is None:
        login_end = login_end.replace(tzinfo=timezone.utc)

    if login_end and login_end < login_start:
        raise HTTPException(
            status_code=422,
            detail="login_datetime_end cannot be earlier than login_datetime_start."
        )

    session_mins = (
        round((login_end - login_start).total_seconds() / 60, 2)
        if login_end else 0.0
    )

    conn = get_pg_connection()

    try:
        with conn:  # commits on success, rolls back on error
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:

                # Serialise concurrent calls for the same user_id.
                cur.execute(
                    "SELECT pg_advisory_xact_lock(hashtext(%s));",
                    (payload.user_id,)
                )

                cur.execute(
                    """
                    SELECT id, total_time_spent_mins
                    FROM public.user_login_details
                    WHERE user_id = %s
                    ORDER BY id DESC
                    LIMIT 1
                    FOR UPDATE;
                    """,
                    (payload.user_id,)
                )
                existing = cur.fetchone()

                if existing:
                    new_total_mins = round(
                        float(existing["total_time_spent_mins"] or 0) + session_mins, 2
                    )

                    cur.execute(
                        f"""
                        UPDATE public.user_login_details
                        SET user_name             = %s,
                            user_email            = %s,
                            user_role             = %s,
                            login_datetime_start  = %s,
                            login_datetime_end    = %s,
                            total_time_spent_mins = %s,
                            total_time_spent_hrs  = %s,
                            updated_at            = NOW()
                        WHERE id = %s
                        RETURNING {USER_LOGIN_COLUMNS};
                        """,
                        (
                            payload.user_name,
                            payload.user_email.lower(),
                            payload.user_role or "admin",
                            login_start,
                            login_end,
                            new_total_mins,
                            round(new_total_mins / 60, 2),
                            existing["id"],
                        )
                    )
                    response.status_code = status.HTTP_200_OK

                else:
                    cur.execute(
                        f"""
                        INSERT INTO public.user_login_details (
                            user_id, user_name, user_email,
                            login_datetime_start, login_datetime_end,
                            user_role, total_time_spent_mins, total_time_spent_hrs
                        )
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                        RETURNING {USER_LOGIN_COLUMNS};
                        """,
                        (
                            payload.user_id,
                            payload.user_name,
                            payload.user_email.lower(),
                            login_start,
                            login_end,
                            payload.user_role or "admin",
                            session_mins,
                            round(session_mins / 60, 2),
                        )
                    )

                row = cur.fetchone()

        return UserLoginResponse(**row)

    except Exception as e:
        print(f"[POST FAILED] Error saving user login: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Database save error: {str(e)}"
        )

    finally:
        conn.close()


# ---------------------------------------------------------
# GET LOGIN USERS (PostgreSQL)
# ---------------------------------------------------------

@app.get(
    "/api/login-users",
    response_model=List[UserLoginResponse]
)
def get_login_users(
    user_id: Optional[str] = Query(None, description="Filter by user_id"),
    user_email: Optional[str] = Query(None, description="Filter by email"),
    user_role: Optional[str] = Query(None, description="Filter by role"),
    limit: int = Query(100, ge=1, le=1000, description="Max rows to return"),
    offset: int = Query(0, ge=0, description="Rows to skip (for paging)")
):
    """
    Returns user login records, newest first.
    All filters are optional; with none, returns the latest 100 records.
    """

    conditions = []
    params = []

    if user_id:
        conditions.append("user_id = %s")
        params.append(user_id)

    if user_email:
        conditions.append("LOWER(user_email) = LOWER(%s)")
        params.append(user_email)

    if user_role:
        conditions.append("user_role = %s")
        params.append(user_role)

    where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""

    select_query = f"""
        SELECT {USER_LOGIN_COLUMNS}
        FROM public.user_login_details
        {where_clause}
        ORDER BY login_datetime_start DESC
        LIMIT %s OFFSET %s;
    """
    params.extend([limit, offset])

    conn = get_pg_connection()

    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(select_query, params)
            rows = cur.fetchall()

        return [UserLoginResponse(**row) for row in rows]

    except Exception as e:
        print(f"[GET FAILED] Error querying user logins: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Database query error: {str(e)}"
        )

    finally:
        conn.close()


# ---------------------------------------------------------
# DELETE ALL LOGIN USERS (PostgreSQL)
# ---------------------------------------------------------

@app.delete("/api/login-users")
def delete_all_login_users(
    confirm: bool = Query(
        False,
        description="Must be true to delete. Prevents accidental wipes."
    )
):
    """
    Permanently deletes ALL records from user_login_details.
    Requires ?confirm=true. This cannot be undone.
    """

    if not confirm:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="This deletes ALL login records. Call again with ?confirm=true to proceed."
        )

    conn = get_pg_connection()

    try:
        with conn:  # commits on success, rolls back on error
            with conn.cursor() as cur:
                cur.execute("DELETE FROM public.user_login_details;")
                deleted = cur.rowcount

        return {
            "message": "All login records deleted.",
            "deleted_count": deleted
        }

    except Exception as e:
        print(f"[DELETE FAILED] Error deleting user logins: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Database delete error: {str(e)}"
        )

    finally:
        conn.close()

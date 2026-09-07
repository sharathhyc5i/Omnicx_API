
import os
import struct
import pyodbc

from typing import List

from pydantic import BaseModel
from fastapi import (
    FastAPI,
    HTTPException,
    Header,
    status
)
from fastapi.middleware.cors import CORSMiddleware


# =========================================================
# FASTAPI APPLICATION
# =========================================================

app = FastAPI(
    title="OmniCX Python ODBC Companion Backend",
    description=(
        "Read-only API exposing SQL Server "
        "[dbo].[CXReport_DisplayName_MetricPercents] "
        "records to the React Frontend Dashboard."
    ),
    version="1.0.0"
)


# =========================================================
# CORS
# =========================================================

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Restrict this in production
    allow_credentials=True,
    allow_methods=["GET"],
    allow_headers=["*"],
)


# =========================================================
# SQL SERVER CONFIGURATION
# =========================================================

SQL_SERVER = os.getenv(
    "SQL_SERVER",
    "AZPWRSSQL003"
)

SQL_DATABASE = os.getenv(
    "SQL_DATABASE",
    "WWRCM_PowerBI"
)

SQL_DRIVER = os.getenv(
    "SQL_DRIVER",
    "ODBC Driver 18 for SQL Server"
)

# =========================================================
# DEVELOPMENT TEST TOKEN
# =========================================================

DEV_ACCESS_TOKEN = os.getenv(
    "DEV_ACCESS_TOKEN",
    "TEST_ACCESS_TOKEN_FOR_LOCAL_DEVELOPMENT_ONLY"
)


# =========================================================
# MICROSOFT ODBC ACCESS TOKEN CONSTANT
# =========================================================

# SQL_COPT_SS_ACCESS_TOKEN
#
# This tells Microsoft ODBC Driver 18 that the
# authentication token is being supplied manually.
#
# IMPORTANT:
# Do NOT add:
#
# Authentication=ActiveDirectoryIntegrated;
#
# when using this approach.
# =========================================================

SQL_COPT_SS_ACCESS_TOKEN = 1256


# =========================================================
# RESPONSE MODEL
# =========================================================

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


# =========================================================
# TOKEN HELPER
# =========================================================

def clean_access_token(authorization: str) -> str:
    """
    Extracts the raw Microsoft Entra ID access token
    from the Authorization header.

    Expected:

        Authorization: Bearer eyJhbGciOi...

    Returns:

        eyJhbGciOi...
    """

    if not authorization:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authorization header is required"
        )

    authorization = authorization.strip()

    if authorization.lower().startswith("bearer "):

        token = authorization[7:].strip()

    else:

        # Also allow a raw token if required
        token = authorization

    if not token:

        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Access token is empty"
        )

    return token


# =========================================================
# SQL SERVER CONNECTION
# =========================================================

def get_db_connection(access_token: str):
    """
    Creates a SQL Server connection using the
    Microsoft Entra ID access token received
    from the frontend.

    Authentication flow:

        React
          |
          | Bearer token
          v
        FastAPI
          |
          | Access token
          v
        ODBC Driver 18
          |
          v
        SQL Server


    IMPORTANT:

    The access token must be intended for SQL Server /
    Azure SQL resource:

        https://database.windows.net/

    Do NOT use:

        Authentication=ActiveDirectoryIntegrated

    when supplying the access token manually.
    """

    try:

        # -------------------------------------------------
        # Clean Bearer prefix
        # -------------------------------------------------


        token = clean_access_token(
            access_token
        )

        print(
            "[DB] Access token received from frontend"
        )

      
        token_bytes = token.encode(
            "utf-16-le"
        )

       

        token_struct = struct.pack(
            f"<I{len(token_bytes)}s",
            len(token_bytes),
            token_bytes
        )

       

        connection_string = (
            f"Driver={{{SQL_DRIVER}}};"
            f"Server={SQL_SERVER};"
            f"Database={SQL_DATABASE};"
            "Encrypt=yes;"
            "TrustServerCertificate=yes;"
            "Connection Timeout=30;"
        )

        print(
            f"[DB] Server: {SQL_SERVER}"
        )

        print(
            f"[DB] Database: {SQL_DATABASE}"
        )

        # -------------------------------------------------
        # Connect using Microsoft Entra ID token
        # -------------------------------------------------

        connection = pyodbc.connect(
            connection_string,
            attrs_before={
                SQL_COPT_SS_ACCESS_TOKEN: token_struct
            }
        )

        print(
            "[DB] SQL Server connection successful"
        )

        return connection

    except pyodbc.Error as e:

        print(
            "[DB ERROR] ODBC connection failed:"
        )

        print(
            str(e)
        )

        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Database connection failed: {str(e)}"
        )

    except Exception as e:

        print(
            "[DB ERROR] SQL Server connection failed:"
        )

        print(
            str(e)
        )

        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Database connection failed: {str(e)}"
        )


# =========================================================
# HEALTH CHECK
# =========================================================

@app.get("/api/health")
def health_check():

    return {
        "status": "online"
    }


# =========================================================
# DATABASE HEALTH CHECK
# =========================================================

@app.get("/api/db-health")
def database_health_check(
    authorization: str = Header(None)
):

    conn = None
    cursor = None

    try:

        # -------------------------------------------------
        # Validate Authorization header
        # -------------------------------------------------

        if not authorization:

            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Authorization header is required"
            )

        # -------------------------------------------------
        # Connect to database
        # -------------------------------------------------

        conn = get_db_connection(
            authorization
        )

        cursor = conn.cursor()

        # -------------------------------------------------
        # Simple database test
        # -------------------------------------------------

        cursor.execute(
            "SELECT 1 AS database_connection"
        )

        row = cursor.fetchone()

        return {
            "status": "connected",
            "server": SQL_SERVER,
            "database": SQL_DATABASE,
            "result": (
                row[0]
                if row
                else None
            )
        }

    except HTTPException:

        raise

    except Exception as e:

        print(
            f"[DB HEALTH ERROR] {str(e)}"
        )

        raise HTTPException(
            status_code=500,
            detail=(
                f"Database health check failed: "
                f"{str(e)}"
            )
        )

    finally:

        # -------------------------------------------------
        # Close cursor
        # -------------------------------------------------

        if cursor is not None:

            cursor.close()

        # -------------------------------------------------
        # Close connection
        # -------------------------------------------------

        if conn is not None:

            conn.close()


# =========================================================
# GET DISPLAY RECORDS
# =========================================================

@app.get(
    "/api/display",
    response_model=List[DisplayItem]
)
def get_all_records(
    authorization: str = Header(None)
):

    conn = None
    cursor = None

    try:

        # -------------------------------------------------
        # Validate Authorization header
        # -------------------------------------------------

        if not authorization:

            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Authorization header is required"
            )

        # -------------------------------------------------
        # Connect to SQL Server using the token
        # received from frontend
        # -------------------------------------------------

        conn = get_db_connection(
            authorization
        )

        cursor = conn.cursor()

        # -------------------------------------------------
        # SQL QUERY
        # -------------------------------------------------

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

        print(
            "[DB] Executing DISPLAY query..."
        )

        cursor.execute(
            select_query
        )

        # -------------------------------------------------
        # Get column names
        # -------------------------------------------------

        columns = [
            column[0]
            for column in cursor.description
        ]

        # -------------------------------------------------
        # Fetch records
        # -------------------------------------------------

        rows = cursor.fetchall()

        print(
            f"[DB] Records fetched: {len(rows)}"
        )

        results = []

        # -------------------------------------------------
        # Convert SQL rows to API response
        # -------------------------------------------------

        for row in rows:

            row_dict = dict(
                zip(
                    columns,
                    row
                )
            )

            results.append(
                DisplayItem(

                    partner_display_name=(
                        row_dict.get(
                            "partner_display_name"
                        )
                        or ""
                    ),

                    month_end=(
                        str(
                            row_dict.get(
                                "month_end"
                            )
                        )
                        if row_dict.get(
                            "month_end"
                        ) is not None
                        else ""
                    ),

                    sales_hours_compliance_percent=float(
                        row_dict.get(
                            "sales_hours_compliance_percent"
                        )
                        or 0.0
                    ),

                    pa_hours_compliance_percent=float(
                        row_dict.get(
                            "pa_hours_compliance_percent"
                        )
                        or 0.0
                    ),

                    mm_hours_compliance_percent=float(
                        row_dict.get(
                            "mm_hours_compliance_percent"
                        )
                        or 0.0
                    ),

                    win_essentials_completion_percent=float(
                        row_dict.get(
                            "win_essentials_completion_percent"
                        )
                        or 0.0
                    ),

                    mshop_ee_points_percent=float(
                        row_dict.get(
                            "mshop_ee_points_percent"
                        )
                        or 0.0
                    ),

                    mshop_ba_points_percent=float(
                        row_dict.get(
                            "mshop_ba_points_percent"
                        )
                        or 0.0
                    ),

                    wots_submission_percent=float(
                        row_dict.get(
                            "wots_submission_percent"
                        )
                        or 0.0
                    ),

                    wots_quality_submission_percent=float(
                        row_dict.get(
                            "wots_quality_submission_percent"
                        )
                        or 0.0
                    ),

                    wots_windows_positive_sentiment_percent=float(
                        row_dict.get(
                            "wots_windows_positive_sentiment_percent"
                        )
                        or 0.0
                    )
                )
            )

        return results

    except HTTPException:

        raise

    except pyodbc.Error as e:

        print(
            "[GET FAILED] SQL Server error:"
        )

        print(
            str(e)
        )

        raise HTTPException(
            status_code=500,
            detail=(
                f"Database query error: "
                f"{str(e)}"
            )
        )

    except Exception as e:

        print(
            "[GET FAILED] Unexpected error:"
        )

        print(
            str(e)
        )

        raise HTTPException(
            status_code=500,
            detail=(
                f"Database query error: "
                f"{str(e)}"
            )
        )

    finally:

        # -------------------------------------------------
        # Close cursor
        # -------------------------------------------------

        if cursor is not None:

            cursor.close()

        # -------------------------------------------------
        # Close connection
        # -------------------------------------------------

        if conn is not None:

            conn.close()


# =========================================================
# START APPLICATION
# =========================================================

if __name__ == "__main__":

    import uvicorn

    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=int(
            os.getenv(
                "PORT",
                "8000"
            )
        ),
        reload=False
    )


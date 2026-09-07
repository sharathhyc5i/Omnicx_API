import os
import pyodbc

from typing import List
from pydantic import BaseModel
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
        "records to the React Frontend Dashboard."
    ),
    version="1.0.0"
)


# ---------------------------------------------------------
# CORS
# ---------------------------------------------------------

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Restrict this in production
    allow_credentials=True,
    allow_methods=["GET"],
    allow_headers=["*"],
)


# ---------------------------------------------------------
# SQL Server Connection
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
    Creates a read-only database connection.

    The connection string can be supplied through the
    SQL_SERVER_CONN_STR environment variable.
    """

    conn_str = os.getenv(
        "SQL_SERVER_CONN_STR",
        DEFAULT_CONN_STR
    )

    try:
        return pyodbc.connect(conn_str)

    except Exception as e:
        print(f"[DB ERROR] ODBC Connection to SQL Server failed: {e}")

        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Database connection failed: {str(e)}"
        )


# ---------------------------------------------------------
# Response Model
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


# ---------------------------------------------------------
# Health Check
# ---------------------------------------------------------

@app.get("/api/health")
def health_check():
    return {
        "status": "online"
    }


# ---------------------------------------------------------
# GET DISPLAY RECORDS
# ---------------------------------------------------------

@app.get(
    "/api/display",
    response_model=List[DisplayItem]
)
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

        results = []

        for row in rows:

            row_dict = dict(zip(columns, row))

            results.append(
                DisplayItem(

                    partner_display_name=(
                        row_dict.get("partner_display_name")
                        or ""
                    ),

                    month_end=(
                        str(row_dict.get("month_end"))
                        if row_dict.get("month_end") is not None
                        else ""
                    ),

                    sales_hours_compliance_percent=float(
                        row_dict.get(
                            "sales_hours_compliance_percent"
                        ) or 0.0
                    ),

                    pa_hours_compliance_percent=float(
                        row_dict.get(
                            "pa_hours_compliance_percent"
                        ) or 0.0
                    ),

                    mm_hours_compliance_percent=float(
                        row_dict.get(
                            "mm_hours_compliance_percent"
                        ) or 0.0
                    ),

                    win_essentials_completion_percent=float(
                        row_dict.get(
                            "win_essentials_completion_percent"
                        ) or 0.0
                    ),

                    mshop_ee_points_percent=float(
                        row_dict.get(
                            "mshop_ee_points_percent"
                        ) or 0.0
                    ),

                    mshop_ba_points_percent=float(
                        row_dict.get(
                            "mshop_ba_points_percent"
                        ) or 0.0
                    ),

                    wots_submission_percent=float(
                        row_dict.get(
                            "wots_submission_percent"
                        ) or 0.0
                    ),

                    wots_quality_submission_percent=float(
                        row_dict.get(
                            "wots_quality_submission_percent"
                        ) or 0.0
                    ),

                    wots_windows_positive_sentiment_percent=float(
                        row_dict.get(
                            "wots_windows_positive_sentiment_percent"
                        ) or 0.0
                    )
                )
            )

        return results

    except Exception as e:

        print(
            f"[GET FAILED] Error querying DISPLAY table: {e}"
        )

        raise HTTPException(
            status_code=500,
            detail=f"Database query error: {str(e)}"
        )

    finally:

        cursor.close()
        conn.close()
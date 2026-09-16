import pymysql
import pymysql.cursors
import os
import re
from config import Config


def initialize_database():
    """Create missing LMS tables when explicitly enabled for first deployment."""
    if os.environ.get("AUTO_INIT_DB") != "1":
        return

    with open(os.path.join(Config.BASE_DIR, "schema.sql"), encoding="utf-8") as schema_file:
        schema = schema_file.read()

    schema = re.sub(r"--.*", "", schema)
    statements = [
        statement.strip()
        for statement in schema.split(";")
        if statement.strip() and not statement.strip().upper().startswith(("CREATE DATABASE", "USE "))
    ]

    connection = get_db_connection()
    try:
        with connection.cursor() as cursor:
            for statement in statements:
                cursor.execute(statement)
    finally:
        connection.close()

def get_db_connection():
    """
    Establishes and returns a connection to the MySQL database.
    It automatically uses DictCursor to return rows as dictionary-like objects.
    """
    return pymysql.connect(
        host=Config.DB_HOST,
        port=Config.DB_PORT,
        user=Config.DB_USER,
        password=Config.DB_PASSWORD,
        database=Config.DB_NAME,
        cursorclass=pymysql.cursors.DictCursor,
        autocommit=True
    )

def fetch_all(query, params=None):
    """
    Executes a SELECT query and returns all matching rows as a list of dictionaries.
    """
    connection = get_db_connection()
    try:
        with connection.cursor() as cursor:
            cursor.execute(query, params or ())
            return cursor.fetchall()
    except Exception as e:
        print(f"Database Fetch All Error: {e}")
        raise e
    finally:
        connection.close()

def fetch_one(query, params=None):
    """
    Executes a SELECT query and returns the first matching row as a dictionary, or None.
    """
    connection = get_db_connection()
    try:
        with connection.cursor() as cursor:
            cursor.execute(query, params or ())
            return cursor.fetchone()
    except Exception as e:
        print(f"Database Fetch One Error: {e}")
        raise e
    finally:
        connection.close()

def execute_query(query, params=None, return_lastrowid=False):
    """
    Executes an INSERT, UPDATE, or DELETE query.
    Returns the last inserted row ID (for INSERTs if requested) or the number of affected rows.
    """
    connection = get_db_connection()
    try:
        with connection.cursor() as cursor:
            affected_rows = cursor.execute(query, params or ())
            if return_lastrowid:
                return cursor.lastrowid
            return affected_rows
    except Exception as e:
        print(f"Database Execution Error: {e}")
        raise e
    finally:
        connection.close()

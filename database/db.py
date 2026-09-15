import pymysql
import pymysql.cursors
from config import Config

def get_db_connection():
    """
    Establishes and returns a connection to the MySQL database.
    It automatically uses DictCursor to return rows as dictionary-like objects.
    """
    return pymysql.connect(
    host=Config.DB_HOST,
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

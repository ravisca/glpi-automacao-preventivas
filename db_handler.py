# Integrador com o banco de dados

import mysql.connector
import logging

def connect_db(config):
    """Estabelece e retorna uma conexão com o banco de dados."""
    try:
        connection = mysql.connector.connect(
            host=config['database']['host'],
            user=config['database']['user'],
            password=config['database']['password'],
            database=config['database']['database'],
            charset='utf8mb4'
        )
        if connection.is_connected():
            logging.info("Conexão com o banco de dados estabelecida com sucesso.")
            return connection
    except mysql.connector.Error as e:
        logging.error(f"Erro ao conectar ao MariaDB: {e}")
        return None

def close_db(connection):
    """Fecha a conexão com o banco de dados."""
    if connection and connection.is_connected():
        connection.close()
        logging.info("Conexão com o banco de dados fechada.")

def fetch_all(connection, query, params=None):
    """Executa uma consulta SELECT e retorna todas as linhas."""
    cursor = connection.cursor(dictionary=True)
    try:
        cursor.execute(query, params or ())
        results = cursor.fetchall()
        return results
    except mysql.connector.Error as e:
        logging.error(f"Erro ao executar a consulta (fetch_all): {e}")
        return []
    finally:
        cursor.close()

def fetch_one(connection, query, params=None):
    """Executa uma consulta SELECT e retorna uma única linha."""
    cursor = connection.cursor(dictionary=True)
    try:
        cursor.execute(query, params or ())
        result = cursor.fetchone()
        return result
    except mysql.connector.Error as e:
        logging.error(f"Erro ao executar a consulta (fetch_one): {e}")
        return None
    finally:
        cursor.close()

def execute_insert(connection, query, params=None):
    """Executa uma consulta INSERT e retorna o ID da nova linha."""
    cursor = connection.cursor()
    try:
        cursor.execute(query, params or ())
        connection.commit()
        last_id = cursor.lastrowid
        logging.info(f"Registro inserido com sucesso. ID: {last_id}")
        return last_id
    except mysql.connector.Error as e:
        logging.error(f"Erro ao executar a inserção: {e}")
        connection.rollback()
        return None
    finally:
        cursor.close()

def execute_update(connection, query, params=None):
    """Executa uma consulta UPDATE e retorna o número de linhas afetadas."""
    cursor = connection.cursor()
    try:
        cursor.execute(query, params or ())
        connection.commit()
        row_count = cursor.rowcount
        logging.info(f"{row_count} linha(s) afetada(s) pela atualização.")
        return row_count
    except mysql.connector.Error as e:
        logging.error(f"Erro ao executar a atualização: {e}")
        connection.rollback()
        return None
    finally:
        cursor.close()
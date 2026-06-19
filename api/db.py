

import mysql


def get_db_connection():
    return mysql.connector.connect(
        # host="127.0.0.1",
        # user="root",
        # password="",
        # database="mydb",
        host = "bwr2tjeeysysm7um7pfo-mysql.services.clever-cloud.com",
        user = "ucg3v1n4o6kbgzk2",
        password = "8CJNC9GDRkkpe5kPvzJw",
        database = "bwr2tjeeysysm7um7pfo"
    )

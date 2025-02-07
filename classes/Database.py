import sqlite3
from typing import Union

from classes.QuestionData import QuestionData


class EventAlreadyLockedException(Exception):
    pass


class dbopen(object):
    """
    Simple CM for sqlite3 databases. Commits everything at exit.
    """

    def __init__(self, path):
        self.path = path

    def __enter__(self):
        self.conn = sqlite3.connect(self.path, detect_types=sqlite3.PARSE_DECLTYPES |
                                                            sqlite3.PARSE_COLNAMES)
        self.conn.row_factory = sqlite3.Row
        self.cursor = self.conn.cursor()
        return self.cursor

    def __exit__(self, exc_class, exc, traceback):
        self.conn.commit()
        self.conn.close()


class Database(dbopen):
    def __init__(self, path="question_data.db", schema_file="schema.sql", folder=""):
        super().__init__(folder + path)
        with self as cursor:
            with open(folder + schema_file) as schema:
                cursor.executescript(schema.read())

    def __contains__(self, item: str):
        """
        first checks if primary hash exists, if not then checks if secondary hash exists.
        since chances of collission with md5 is less, wrt to the context used, this method should
        suffice to determine if primary or secondary hash exist or not
        """
        with self as cursor:
            to_try = ["primary_hash", "secondary_hash"]
            for hash_table in to_try:
                cursor.execute("SELECT * FROM question_data WHERE {} = ?".format(hash_table), (item,))
                output = cursor.fetchall()
                if len(output) != 0 and item in output[0]:
                    return True
        return False

    def insert(self, question_data: QuestionData):
        query = "INSERT INTO question_data VALUES (?, ?, ?, ?, ?, ?);"
        with self as cursor:
            cursor.execute(query, (
                question_data.class_name, question_data.due_date, question_data.question, question_data.q_type,
                question_data.primary_hash, question_data.secondary_hash))

            if question_data.message_id:  # this will always execute when in production
                cursor.execute("INSERT INTO message_ids VALUES (?, ?);",
                               (question_data.primary_hash, question_data.message_id))

    def remove(self, question_data: QuestionData):
        tables = ["question_data", "message_ids"]
        query = "DELETE FROM {} WHERE primary_hash = ?"
        with self as cursor:
            for table in tables:
                cursor.execute(query.format(table), (question_data.primary_hash,))

        # confirmation
        with self as cursor:
            cursor.execute("SELECT * FROM question_data WHERE primary_hash = ?", (question_data.primary_hash,))
            output = cursor.fetchall()
            assert len(output) == 0

    def get_via_secondary_hash(self, hash: str) -> QuestionData:
        """Returns QuestionData object retrieved via secondary hash"""
        with self as cursor:
            cursor.execute("SELECT * FROM question_data WHERE secondary_hash = ?", (hash,))
            output = cursor.fetchone()
            if output is None:
                raise ValueError("No entry exists for secondary hash")

            cursor.execute("SELECT message_id FROM message_ids WHERE primary_hash = ?", (output["primary_hash"],))
            message_id = cursor.fetchone()

        question = dict(output)
        question["q_type"] = question["question_type"]
        del question["question_type"], question["primary_hash"], question["secondary_hash"]
        q_data = QuestionData(**question)
        q_data.message_id = message_id["message_id"]
        return q_data

    def lock(self, event: QuestionData) -> bool:
        """
        Locks the passed event by storing it in db for other instances to see
        raises exception if event is already present aka already locked
        """
        try:
            with self as cursor:
                cursor.execute("INSERT INTO lock VALUES (?)", (event.primary_hash, ))
        except sqlite3.IntegrityError:
            raise EventAlreadyLockedException
        else:
            return True

    def unlock(self, event: QuestionData):
        """
        Removes the locked event.
        """
        with self as cursor:
            cursor.execute("DELETE FROM lock WHERE primary_hash = ?", (event.primary_hash,))


if __name__ == '__main__':
    import os
    from copy import copy
    from datetime import datetime

    os.chdir("../db")

    db = Database()
    print("Random key in db:", "abcd" in db)
    assert "abcd" not in db

    q = QuestionData("question", "os", "A", datetime(year=2022, month=2, day=10))
    db.insert(q)
    print("new q in db", q.primary_hash in db)
    assert q.primary_hash in db

    q1 = copy(q)
    q1.q_type = "P"
    db.remove(q)
    db.insert(q1)
    print("after modify, q in db:", q.primary_hash in db)
    assert q.primary_hash not in db
    print("after modify, q secondary in db", q.secondary_hash in db)
    assert q.secondary_hash in db
    db.remove(q1)

    print("====")
    q.message_id = "123456789012345678"
    db.insert(q)
    print(db.get_via_secondary_hash(q.secondary_hash))
    db.remove(q)

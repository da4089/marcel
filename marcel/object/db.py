# This file is part of Marcel.
# 
# Marcel is free software: you can redistribute it and/or modify it
# under the terms of the GNU General Public License as published by the
# Free Software Foundation, either version 3 of the License, or at your
# option) any later version.
# 
# Marcel is distributed in the hope that it will be useful, but WITHOUT
# ANY WARRANTY; without even the implied warranty of MERCHANTABILITY or
# FITNESS FOR A PARTICULAR PURPOSE.  See the GNU General Public License
# for more details.
# 
# You should have received a copy of the GNU General Public License
# along with Marcel.  If not, see <https://www.gnu.org/licenses/>.

try:
    import psycopg2
except ModuleNotFoundError:
    pass

import marcel.exception


class Database:

    def __init__(self, name, connection_class, dbname, user, password, host, port):
        self.name = name
        self.connection_class = connection_class
        self.dbname = dbname
        self.user = user
        self.password = password
        self.host = host
        self.port = port

    def connection(self):
        return self.connection_class(self)


class Connection:

    def __init__(self, connection):
        self.connection = connection

    def set_autocommit(self, autocommit):
        self.connection.autocommit = autocommit

    def query(self, sql, args):
        with self.connection.cursor() as cursor:
            cursor.execute(sql, args)
            return cursor.fetchall()

    def insert(self, sql, args):
        with self.connection.cursor() as cursor:
            cursor.execute(sql, args)
            return cursor.rowcount

    def execute(self, sql, args):
        with self.connection.cursor() as cursor:
            cursor.execute(sql, args)
            return cursor.rowcount

    def commit(self):
        self.connection.commit()

    def rollback(self):
        self.connection.rollback()

    def close(self):
        self.connection.close()


class Psycopg2Connection(Connection):

    def __init__(self, db):
        connection = psycopg2.connect(dbname=db.dbname,
                                      user=db.user,
                                      password=db.password,
                                      host=db.host,
                                      posrt=db.port)
        super().__init__(connection)

    # def insert(self, sql, args):
    #     # TODO: Use cursor.mogrify
    #     assert False


def define_db(name, driver, dbname, user, password=None, host=None, port=None):
    if driver == 'psycopg2':
        return Database(name, Psycopg2Connection, dbname, user, password, host, port)
    else:
        raise marcel.exception.KillCommandException(f'Unsupported database driver: {driver}')

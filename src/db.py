import sqlite3
import redis

from src import log, env

logger = log.getLogger('RSStT.db')

if env.REDIS_HOST or env.REDIS_PORT or env.REDIS_USER or env.REDIS_PASSWORD or env.REDIS_NUM:
    #  REDIS
    class DB:
        _pool = redis.ConnectionPool(host=env.REDIS_HOST,
                                     port=6379 if not env.REDIS_PORT else env.REDIS_PORT,
                                     username=env.REDIS_USER,
                                     password=env.REDIS_PASSWORD,
                                     db=0 if not env.REDIS_NUM else env.REDIS_NUM,
                                     socket_connect_timeout=1.5,
                                     socket_timeout=1.5,
                                     retry_on_timeout=True,
                                     decode_responses=True)

        def __init__(self):
            self.feed_dict = {}
            try:
                self._rds = redis.Redis(connection_pool=DB._pool)
                self.load_all()
            except Exception as e:
                logger.critical('Cannot connect to redis!', exc_info=e)
                exit(1)

        def load_all(self):
            if self.feed_dict:
                self.feed_dict.clear()
            keys = self._rds.keys()
            for key in keys:
                link, last = self._rds.hmget(key, 'link', 'last')
                self.feed_dict[key] = (link, last)

        def read(self, name):
            return self.feed_dict.get(name)

        def read_all(self):
            return self.feed_dict

        def write(self, name, link, last, update=False):
            self._rds.hmset(name, {'link': link, 'last': last})
            self.feed_dict[name] = (link, last)

        def delete(self, name):
            self._rds.delete(name)
            del self.feed_dict[name]


else:
    # SQLITE
    class DB:
        def __init__(self):
            self._conn = None
            self.feed_dict = {}
            self._init()
            self.load_all()

        def _init(self):
            try:
                self._conn = sqlite3.connect('config/rss.db', check_same_thread=False)
                c = self._conn.cursor()
                c.execute('''CREATE TABLE rss (name text, link text, last text)''')
            except sqlite3.OperationalError:
                pass

        def load_all(self):
            c = self._conn.cursor()
            c.execute('SELECT * FROM rss')
            rows = c.fetchall()
            if self.feed_dict:
                self.feed_dict.clear()
            for row in rows:
                self.feed_dict[row[0]] = (row[1], row[2])
            return rows

        def read(self, name):
            return self.feed_dict.get(name)

        def read_all(self):
            return self.feed_dict

        def write(self, name, link, last, update=False):
            c = self._conn.cursor()
            p = [last, name]
            q = [name, link, last]
            if update:
                c.execute('''UPDATE rss SET last = ? WHERE name = ?;''', p)
            else:
                c.execute('''INSERT INTO rss('name','link','last') VALUES(?,?,?)''', q)
            self._conn.commit()
            self.feed_dict[name] = (link, last)

        def delete(self, name):
            c = self._conn.cursor()
            q = (name,)
            c.execute("DELETE FROM rss WHERE name = ?", q)
            self._conn.commit()
            del self.feed_dict[name]

db = DB()

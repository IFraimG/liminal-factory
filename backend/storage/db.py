import json, sqlite3, time
from pathlib import Path

class Store:
    def __init__(self,path:Path):
        path.parent.mkdir(parents=True,exist_ok=True)
        self.db=sqlite3.connect(path,check_same_thread=False)
        self.db.row_factory=sqlite3.Row
        self.db.executescript('''PRAGMA journal_mode=WAL;
        CREATE TABLE IF NOT EXISTS episodes(id TEXT PRIMARY KEY, config TEXT NOT NULL, created REAL NOT NULL);
        CREATE TABLE IF NOT EXISTS tasks(episode TEXT, name TEXT, status TEXT DEFAULT 'Pending', error TEXT DEFAULT '', data TEXT DEFAULT '{}', started REAL, finished REAL, PRIMARY KEY(episode,name));
        CREATE TABLE IF NOT EXISTS logs(id INTEGER PRIMARY KEY AUTOINCREMENT,episode TEXT,task TEXT,message TEXT,created REAL);
        CREATE TABLE IF NOT EXISTS versions(id TEXT PRIMARY KEY,episode TEXT NOT NULL,created REAL NOT NULL,status TEXT NOT NULL,revision_id TEXT,video TEXT NOT NULL,manifest TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS revisions(id TEXT PRIMARY KEY,episode TEXT NOT NULL,created REAL NOT NULL,status TEXT NOT NULL,prompt TEXT NOT NULL,provider TEXT NOT NULL,model TEXT,effort TEXT,scope TEXT NOT NULL,data TEXT NOT NULL DEFAULT '{}',error TEXT NOT NULL DEFAULT '');
        CREATE TABLE IF NOT EXISTS metadata_rounds(id TEXT PRIMARY KEY,episode TEXT NOT NULL,created REAL NOT NULL,request TEXT NOT NULL,status TEXT NOT NULL,data TEXT NOT NULL DEFAULT '{}',error TEXT NOT NULL DEFAULT '');
        CREATE TABLE IF NOT EXISTS settings(id INTEGER PRIMARY KEY CHECK(id=1),data TEXT);
        CREATE TABLE IF NOT EXISTS cache(key TEXT PRIMARY KEY,data TEXT,created REAL);
        ''')
        self.db.commit()
    def execute(self,sql,args=()):
        cur=self.db.execute(sql,args); self.db.commit(); return cur
    def rows(self,sql,args=()): return [dict(r) for r in self.db.execute(sql,args)]
    def task(self,e,n):
        r=self.rows('SELECT * FROM tasks WHERE episode=? AND name=?',(e,n))[0]
        r['data']=json.loads(r['data']); return r
    def update(self,e,n,status=None,error=None,data=None):
        t=self.task(e,n)
        self.execute('UPDATE tasks SET status=?,error=?,data=?,started=?,finished=? WHERE episode=? AND name=?',(
            status or t['status'],error if error is not None else t['error'],json.dumps(data if data is not None else t['data']),
            None if status=='Pending' else time.time() if status=='Running' and t['started'] is None else t['started'],None if status=='Pending' else time.time() if status in ('Completed','Approved','Failed','Cancelled') else t['finished'],e,n))
    def log(self,e,n,msg): self.execute('INSERT INTO logs(episode,task,message,created) VALUES(?,?,?,?)',(e,n,msg,time.time()))
    def config(self,e):
        r=self.rows('SELECT config FROM episodes WHERE id=?',(e,))
        if not r: raise KeyError('Episode not found')
        return json.loads(r[0]['config'])

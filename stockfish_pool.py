# for mac with apple silicon
import threading

import chess


class StockfishPool:
    def __init__(self, path: str, max_size: int):
        self.path = path
        self.max_size = max_size
        self.pool = []
        self.lock = threading.Lock()

    def get_engine(self, skill_level: int):
        with self.lock:
            if self.pool:
                engine = self.pool.pop()
            else:
                engine = chess.engine.SimpleEngine.popen_uci(self.path)
            
            engine.configure({"Skill Level": skill_level})
            return engine

    def return_engine(self, engine):
        with self.lock:
            if len(self.pool) < self.max_size:
                self.pool.append(engine)
            else:
                engine.quit()

from typing import Any, Dict

from pymongo import MongoClient

# client = MongoClient(host='127.0.0.1', port=27017)
client = MongoClient(host='mongo_db', port=27017, username='zhaoyun', password='801129')

db = client['ichess']
players = db['players']


def load(pid: str) -> Dict[str, Any]:
    return players.find_one({'pid': pid}, {'_id': 0})


def upsert(user: Dict[str, Any]) -> Dict[str, Any]:
    result = players.update_one(
        filter={'pid': user['pid']},
        update={'$set': user},
        upsert=True
    )

    return result.acknowledged


def delete_user(pid: str) -> bool:
    result = players.delete_one({'pid': pid})
    return result.deleted_count == 1

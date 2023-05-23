#!/usr/bin/env python
import json
import logging
import os
import threading
import time
import uuid
from datetime import datetime

import pylark
import requests
from flask import Flask, request
from sqlalchemy import create_engine

from domain import CardSet, RollRecord
from repo import CardSetORM, CardSetRepo, RollRecordORM, RollRecordRepo


FEISHU_BASE_URL = "https://open.feishu.cn/open-apis"
FEISHU_APP_OPEN_ID = os.environ["FEISHU_APP_OPEN_ID"]


class EmojiType:
    DONE = "DONE"
    THUMBSUP = "THUMBSUP"
    THUMBSDOWN = "ThumbsDown"


class CustomAdapter(logging.LoggerAdapter):
    """
    This example adapter expects the passed in dict-like object to have a
    'req_id' key, whose value in brackets is prepended to the log message.
    """

    def process(self, msg, kwargs):
        return (
            "[{}] {}".format(self.extra["req_id"], msg),
            kwargs,
        )


class TokenManager:
    feishu_cli: pylark.Lark = None
    lock: threading.Lock = None
    token: str = ""
    expire_time: int = 0

    def __init__(self, app_id: str, app_secret: str):
        self.lock = threading.Lock()
        self.feishu_cli = pylark.Lark(app_id=app_id, app_secret=app_secret)

    def get_token(self) -> str:
        with self.lock:
            if self.token and (time.time() + 60) < self.expire_time:
                return self.token
            expire, _ = self.feishu_cli.auth.get_tenant_access_token()
            self.token = expire.token
            self.expire_time = time.time() + expire.expire
            return self.token

    def get_header(self) -> dict:
        token = self.get_token()
        return {"Authorization": "Bearer " + token}


class OpenAI:
    api_key = os.environ["OPENAI_API_KEY"]
    api_base_url = os.environ["OPENAI_API_BASE_URL"]

    @classmethod
    def recognize(self, prompt: str, text: str) -> str:
        head = {"Authorization": "Bearer " + self.api_key}
        data = {
            "model": "gpt-3.5-turbo",
            "messages": [
                {"role": "system", "content": f"{prompt}"},
                {"role": "user", "content": text},
            ],
        }
        url = self.api_base_url + "/v1/chat/completions"
        resp = requests.post(url, headers=head, json=data)
        assert resp.status_code == 200
        return resp.json()["choices"][0]["text"]


class EventHandler:
    logger: CustomAdapter = None
    data: dict = None
    token_manager: TokenManager = None

    def __init__(self, data: dict, token_manager: TokenManager) -> None:
        self.data = data
        self.token_manager = token_manager
        req_id = datetime.now().strftime("%Y%m%d%H%M%S") + str(uuid.uuid4())[:8]
        self.logger = CustomAdapter(_logger, {"req_id": req_id})

    @property
    def chat_type(self) -> str:
        res = self.data.get("event", {}).get("message", {}).get("chat_type", "")
        assert res != ""
        return res

    @property
    def event_type(self) -> str:
        res = self.data.get("header", {}).get("event_type", "")
        assert res != ""
        return res

    @property
    def chat_id(self) -> str:
        res = self.data.get("event", {}).get("message", {}).get("chat_id", "")
        assert res != ""
        return res

    @property
    def sender_id(self) -> str:
        res = (
            self.data.get("event", {})
            .get("sender", {})
            .get("sender_id", {})
            .get("open_id", "")
        )
        assert res != ""
        return res

    @property
    def msg_id(self) -> str:
        res = self.data.get("event", {}).get("message", {}).get("message_id", "")
        if res == "":
            res = self.data.get("event", {}).get("message_id", "")
        assert res != ""
        return res

    @property
    def reaction_emoji(self) -> str:
        res = self.data.get("event", {}).get("reaction_type", {}).get("emoji_type", "")
        assert res != ""
        return res

    @property
    def reaction_operator_type(self) -> str:
        res = self.data.get("event", {}).get("operator_type", "")
        assert res != ""
        return res

    def handle(self):
        try:
            return self._handle()
        except Exception as e:
            self.logger.exception(e)
            return {"msg": "error"}

    def _handle(self):
        self.logger.info("receive data: %s", json.dumps(self.data, ensure_ascii=False))
        if self.event_type == "im.message.receive_v1":
            content = json.loads(self.data["event"]["message"]["content"])
            text: str = content["text"]
            # 忽略群聊内非@机器人的消息、非命令消息
            if self.chat_type == "group":
                mentions = self.data["event"]["message"].get("mentions", [])
                if len(mentions) > 1:
                    return
                elif len(mentions) == 1:
                    if mentions[0]["id"]["open_id"] != FEISHU_APP_OPEN_ID:
                        return
                    text = text.replace(mentions[0]["key"], "")
                elif not text.startswith("/"):
                    return
            text = text.strip()
            if text.startswith("/"):
                self.handle_text(text)
            else:
                self.handle_text_gpt(text)
        elif self.event_type == "im.message.reaction.created_v1":
            self.handle_reaction()
        elif self.event_type == "im.message.reaction.deleted_v1":
            self.handle_reaction(reverse=True)
        else:
            self.logger.warning("unknown event type: %s", self.event_type)
        return {"msg": "ok"}

    def handle_reaction(self, reverse=False):
        if self.reaction_emoji not in [EmojiType.THUMBSUP, EmojiType.THUMBSDOWN]:
            return
        if self.reaction_operator_type != "user":
            return
        record = roll_record_repo.get_roll_record(self.msg_id)
        if not record:
            # self.logger.warning("roll record not found: %s", self.data)
            return
        card_set = card_set_repo.get_card_set(record.chat_id, record.card_set_name)
        if not card_set:
            self.logger.warning("card set not found: %s", self.data)
            return
        card = card_set.get_card(record.card_name)
        if not card:
            self.logger.warning("card not found: %s", self.data)
            return
        num = -1 if reverse else 1
        if self.reaction_emoji == EmojiType.THUMBSUP:
            num = num
        elif self.reaction_emoji == EmojiType.THUMBSDOWN:
            num = -num
        else:
            self.logger.warning("unknown reaction emoji: %s", self.reaction_emoji)
            return
        card_set.set_wight(card.name, card.weight + num)
        card_set_repo.create_or_update_card_set(card_set)
        self.logger.info("update card weight: %s, %d", card, num)

    def handle_text(self, text: str) -> None:
        argv = text.split()
        cmd = argv[0]
        if cmd == "/add":
            return self.handle_add(argv[1:])
        elif cmd == "/ls":
            return self.handle_ls(argv[1:])
        elif cmd == "/del":
            return self.handle_del(argv[1:])
        elif cmd == "/roll":
            return self.handle_roll(argv[1:])
        else:
            title = "使用说明"
            lines = []
            lines.append([{"tag": "text", "text": "增加集合or成员: /add <集合名称> [<成员名称>]"}])
            lines.append([{"tag": "text", "text": "列出集合or成员: /ls [<集合名称>]"}])
            lines.append([{"tag": "text", "text": "删除集合or成员: /del <集合名称> [<成员名称>]"}])
            lines.append([{"tag": "text", "text": "从集合中抽卡: /roll [<集合名称>]"}])
            return self.reply_post(title, lines)

    def handle_text_gpt(self, text: str):
        prompt = """
        有一个抽卡工具，可以用指令创建/修改集合，并随机从集合内抽取元素。支持的指令如下：
- 向集合内增加一个或多个成员：/add 集合名称 成员名称1 成员名称2 ...
- 列出所有集合：/ls
- 列出集合内的成员：/ls 集合名称
- 删除集合：/del_set 集合名称
- 删除集合内的成员：/del_item 集合名称 成员名称
- 从集合中抽卡: /roll 集合名称

你现在扮演一个翻译的角色，将自然语言翻译成具体指令。示例：
"吃饭可以去老乡鸡、和府捞面" -> "/add 吃饭 老乡鸡 和府捞面"
"查看" -> "/ls"
"查看吃饭集合" -> "/ls 吃饭"
"从吃饭里删掉老乡鸡" -> "/del 吃饭 老乡鸡"
"从吃饭里抽一张" -> "/roll 吃饭"

现在，请将下面的自然语言翻译成具体指令。如果无法翻译，请回复"无法理解"
"{}" """
        new_text = OpenAI.recognize(prompt, text)
        self.reply_text(new_text)

    def handle_add(self, argv: list[str]):
        if len(argv) == 1:
            name = argv[0]
            if card_set_repo.get_card_set(self.chat_id, name):
                self.reply_text("集合已存在")
                return
            card_set = CardSet(self.chat_id, name, create_by=self.sender_id)
            card_set_repo.create_or_update_card_set(card_set)
            self.reply_reaction(EmojiType.DONE)
            return
        elif len(argv) >= 2:
            name = argv[0]
            card_set = card_set_repo.get_card_set(self.chat_id, name)
            if not card_set:
                card_set = CardSet(self.chat_id, name, create_by=self.sender_id)
            for item in argv[1:]:
                card_set.add_card(item)
            card_set_repo.create_or_update_card_set(card_set)
            self.reply_reaction(EmojiType.DONE)
            return
        return self.reply_text("/add <集合名称> [<成员名称>]")

    def handle_ls(self, argv: list[str]):
        if len(argv) == 0:
            card_set_list = card_set_repo.get_card_set_list(self.chat_id)
            if not card_set_list:
                self.reply_text("没有集合")
                return
            title = "集合列表"
            lines = []
            for card_set in card_set_list:
                line = []
                line.append(
                    {
                        "tag": "text",
                        "text": "{} ({}个成员)".format(
                            card_set.name, len(card_set.get_cards())
                        ),
                    }
                )
                lines.append(line)
            self.reply_post(title, lines)
            return
        elif len(argv) == 1:
            name = argv[0]
            card_set = card_set_repo.get_card_set(self.chat_id, name)
            if not card_set:
                self.reply_text("集合不存在")
                return
            title = "集合 {} 的成员".format(card_set.name)
            lines = []
            for card in card_set.get_cards():
                line = []
                line.append(
                    {
                        "tag": "text",
                        "text": "{} (权重{})".format(card.name, card.weight),
                    }
                )
                lines.append(line)
            self.reply_post(title, lines)
            return
        return self.reply_text("/ls [<集合名称>]")

    def handle_del(self, argv: list[str]):
        if len(argv) == 1:
            name = argv[0]
            card_set = card_set_repo.get_card_set(self.chat_id, name)
            if not card_set:
                self.reply_text("集合不存在")
                return
            if len(card_set.get_cards()) > 0:
                self.reply_text("集合内有{}个成员, 无法删除非空集合".format(len(card_set.get_cards())))
                return
            card_set_repo.remove_card_set(self.chat_id, name)
            self.reply_reaction(EmojiType.DONE)
            return
        elif len(argv) == 2:
            name, item = argv[0], argv[1]
            card_set = card_set_repo.get_card_set(self.chat_id, name)
            if not card_set:
                self.reply_text("集合不存在")
                return
            removed = card_set.remove_card(item)
            if not removed:
                self.reply_text("成员不存在")
                return
            card_set_repo.create_or_update_card_set(card_set)
            self.reply_reaction(EmojiType.DONE)
            self.reply_text("已删除成员{}, 权重{}".format(removed.name, removed.weight))
            return
        return self.reply_text("/del <集合名称> [<成员名称>]")

    def handle_roll(self, argv: list[str]):
        if len(argv) == 0:
            card_set_list = card_set_repo.get_card_set_list(self.chat_id)
            if len(card_set_list) == 1:
                return self.handle_roll([card_set_list[0].name])
            elif len(card_set_list) == 0:
                self.reply_text("没有集合")
                return
        if len(argv) == 1:
            name = argv[0]
            card_set = card_set_repo.get_card_set(self.chat_id, name)
            if not card_set:
                self.reply_text("集合不存在")
                return
            card = card_set.roll()
            if not card:
                self.reply_text("集合为空")
                return
            title = "抽卡结果"
            lines = [
                [
                    {"tag": "text", "text": "从"},
                    {"tag": "text", "text": card_set.name, "style": ["bold"]},
                    {"tag": "text", "text": "里抽到了"},
                    {"tag": "text", "text": card.name, "style": ["bold"]},
                    {"tag": "text", "text": ", 权重"},
                    {"tag": "text", "text": str(card.weight)},
                ]
            ]
            lines.append([{"tag": "text", "text": "-----------------"}])
            lines.append([{"tag": "text", "text": "在本条消息中回应赞/踩可增减1点权重"}])
            resp = self.reply_post(title, lines)
            msg_id = resp.get("data", {}).get("message_id", "")
            if msg_id:
                record = RollRecord(
                    self.chat_id,
                    card_set.name,
                    card.name,
                    msg_id,
                    self.sender_id,
                )
                roll_record_repo.create_roll_record(record)
                self.reply_reaction(EmojiType.THUMBSUP, msg_id)
                self.reply_reaction(EmojiType.THUMBSDOWN, msg_id)
            return
        return self.reply_text("/roll <集合名称>")

    def reply_reaction(self, emoji_type: str, msg_id: str = None):
        if not msg_id:
            msg_id = self.msg_id
        url = "{}/im/v1/messages/{}/reactions".format(FEISHU_BASE_URL, msg_id)
        data = {"reaction_type": {"emoji_type": emoji_type}}
        resp = requests.post(url, headers=self.token_manager.get_header(), json=data)
        self.logger.info("send reaction %s, response: %s", emoji_type, resp.text)

    def reply_text(self, msg: str):
        url = "{}/im/v1/messages/{}/reply".format(FEISHU_BASE_URL, self.msg_id)
        data = {
            # "content": '{{"text":"<at user_id=\\"{}\\"></at> {}"}}'.format(
            # self.sender_id, msg
            # ),
            "content": '{{"text":"{}"}}'.format(msg),
            "msg_type": "text",
        }
        resp = requests.post(url, headers=self.token_manager.get_header(), json=data)
        self.logger.info("send reply %s, response: %s", msg, resp.text)

    def reply_post(self, title: str, lines: list) -> dict:
        url = "{}/im/v1/messages/{}/reply".format(FEISHU_BASE_URL, self.msg_id)
        content = {
            "zh_cn": {
                "title": title,
                "content": lines,
            }
        }
        data = {
            "content": json.dumps(content, ensure_ascii=False),
            "msg_type": "post",
        }
        resp = requests.post(url, headers=self.token_manager.get_header(), json=data)
        self.logger.info("send post reply %s, response: %s", data["content"], resp.text)
        return resp.json()


def init_db():
    global card_set_repo, roll_record_repo
    engine = create_engine("sqlite:///data/sqlite3.db", echo=True, future=True)
    card_set_repo = CardSetRepo(engine)
    roll_record_repo = RollRecordRepo(engine)
    CardSetORM.metadata.create_all(engine)
    RollRecordORM.metadata.create_all(engine)


def init_logging():
    logging.basicConfig(
        format="%(asctime)s,%(msecs)03d %(levelname)-8s [%(filename)s:%(lineno)d] %(message)s",
        datefmt="%Y-%m-%d:%H:%M:%S",
        level=logging.INFO,
    )
    global _logger
    _logger = logging.getLogger(__name__)
    # _logger.addHandler(logging.StreamHandler())


token_manager = TokenManager(
    os.environ["FEISHU_APP_ID"], os.environ["FEISHU_APP_SECRET"]
)

app = Flask(__name__)


@app.route("/", methods=["GET", "POST"])
def index():
    if request.method == "GET":
        return "<p>Hello, World!</p>"
    data: dict = request.get_json()
    if data.get("challenge"):  # 飞书机器人验证
        return {"challenge": data["challenge"]}
    handler = EventHandler(data, token_manager)
    return handler.handle()


init_db()
init_logging()

if __name__ == "__main__":
    app.run(host="::", port=8080, debug=True)

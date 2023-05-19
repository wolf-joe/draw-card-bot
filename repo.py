#!encoding:utf-8
import json
import time
from sqlalchemy import String, select
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, Session
from sqlalchemy.engine import Engine

from domain import CardSet, RollRecord


class __ORMBase(DeclarativeBase):
    pass


class CardSetORM(__ORMBase):
    __tablename__ = "card_set"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(255))
    chat_id: Mapped[str] = mapped_column(String(255))
    items: Mapped[str] = mapped_column(String(2048))
    created_at: Mapped[int] = mapped_column()
    created_by: Mapped[str] = mapped_column(String(255))
    deleted: Mapped[bool] = mapped_column(default=False)


class CardSetRepo:
    engine: Engine = None

    def __init__(self, engine):
        self.engine = engine

    def __row_to_card_set(self, row: CardSetORM) -> CardSet:
        card_set = CardSet(row.chat_id, row.name, create_by=row.created_by)
        items = json.loads(row.items)
        for item in items:
            card_set.add_card(item["name"], item["weight"])
        return card_set

    def get_card_set_list(self, chat_id: str) -> list[CardSet]:
        session = Session(self.engine)
        stmt = (
            select(CardSetORM)
            .where(CardSetORM.chat_id == chat_id)
            .where(CardSetORM.deleted == False)
        )
        ans = []
        for row in session.scalars(stmt):
            ans.append(self.__row_to_card_set(row))
        return ans

    def get_card_set(self, chat_id: str, name: str) -> CardSet:
        session = Session(self.engine)
        stmt = (
            select(CardSetORM)
            .where(CardSetORM.chat_id == chat_id)
            .where(CardSetORM.name == name)
            .where(CardSetORM.deleted == False)
        )
        for row in session.scalars(stmt):
            return self.__row_to_card_set(row)
        return None

    def create_or_update_card_set(self, card_set: CardSet):
        with Session(self.engine) as session:
            stmt = (
                select(CardSetORM)
                .where(CardSetORM.chat_id == card_set.chat_id)
                .where(CardSetORM.name == card_set.name)
                .where(CardSetORM.deleted == False)
            )
            for row in session.scalars(stmt):
                row.items = json.dumps(
                    card_set.get_cards(),
                    default=lambda o: o.__dict__,
                    ensure_ascii=False,
                )
                assert len(row.items) < 2048
                session.commit()
                return
            else:
                row = CardSetORM()
                row.chat_id = card_set.chat_id
                row.name = card_set.name
                row.items = json.dumps(
                    card_set.get_cards(), default=lambda o: o.__dict__
                )
                row.created_at = time.time()
                row.created_by = card_set.create_by
                session.add(row)
                session.commit()

    def remove_card_set(self, chat_id: str, name: str):
        with Session(self.engine) as session:
            stmt = (
                select(CardSetORM)
                .where(CardSetORM.chat_id == chat_id)
                .where(CardSetORM.name == name)
                .where(CardSetORM.deleted == False)
            )
            for row in session.scalars(stmt):
                row.deleted = True
                session.commit()
                return True
            return False


class RollRecordORM(__ORMBase):
    __tablename__ = "roll_record"
    id: Mapped[int] = mapped_column(primary_key=True)
    chat_id: Mapped[str] = mapped_column(String(255))
    card_set_name: Mapped[str] = mapped_column(String(255))
    card_name: Mapped[str] = mapped_column(String(255))
    msg_id: Mapped[str] = mapped_column(String(255))
    created_by: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[int] = mapped_column()


class RollRecordRepo:
    engine: Engine = None

    def __init__(self, engine):
        self.engine = engine

    def create_roll_record(self, record: RollRecord):
        with Session(self.engine) as session:
            row = RollRecordORM()
            for key in record.__dict__:
                setattr(row, key, record.__dict__[key])
            row.created_at = time.time()
            session.add(row)
            session.commit()

    def get_roll_record(self, msg_id: str) -> RollRecord:
        with Session(self.engine) as session:
            stmt = select(RollRecordORM).where(RollRecordORM.msg_id == msg_id)
            for row in session.scalars(stmt):
                record = RollRecord(
                    chat_id=row.chat_id,
                    card_set_name=row.card_set_name,
                    card_name=row.card_name,
                    msg_id=row.msg_id,
                    created_by=row.created_by,
                )
                return record
            return None

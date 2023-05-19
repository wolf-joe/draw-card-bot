#!/usr/bin/env python

from sqlalchemy import create_engine
from repo import CardSetRepo, CardSetORM
from domain import CardSet

engine = create_engine("sqlite://", echo=True, future=True)
CardSetORM.metadata.create_all(engine)
card_set = CardSet("test_123456", "今天去哪吃饭", create_by="test_user")
card_set.add_card("麦当劳")
card_set.add_card("肯德基")
card_set.set_wight("麦当劳", 20)

card_set_repo = CardSetRepo(engine)
card_set_repo.create_or_update_card_set(card_set)

card_set_list = card_set_repo.get_card_set_list("test_123456")
assert len(card_set_list) == 1
assert card_set_list[0].name == "今天去哪吃饭"
assert len(card_set_list[0].get_cards()) == 2
assert card_set_list[0].get_card("麦当劳").weight == 20

card_set = card_set_list[0]
card_set.add_card("必胜客")
card_set_repo.create_or_update_card_set(card_set)

card_set_list = card_set_repo.get_card_set_list("test_123456")
assert len(card_set_list) == 1
assert len(card_set_list[0].get_cards()) == 3
assert card_set_list[0].get_card("必胜客").weight == 10

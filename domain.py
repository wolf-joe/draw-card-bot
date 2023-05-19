#!encoding:utf-8

from dataclasses import dataclass
import random

DEFAULT_CARD_WIGHT = 10


@dataclass
class Card:
    name: str
    weight: int


@dataclass
class CardSet:
    chat_id: str
    name: str
    cards: list[Card]
    create_by: str

    def __init__(self, chat_id: str, name: str, create_by: str):
        self.chat_id = chat_id
        self.name = name
        self.cards = []
        self.create_by = create_by

    def add_card(self, name: str, weight: int = DEFAULT_CARD_WIGHT):
        if self.get_card(name):
            return
        card = Card(name, weight)
        self.cards.append(card)

    def remove_card(self, name: str) -> Card:
        for card in self.cards:
            if card.name == name:
                self.cards.remove(card)
                return card
        return None

    def get_card(self, name: str) -> Card:
        for card in self.cards:
            if card.name == name:
                return card
        return None

    def get_cards(self) -> list[Card]:
        return self.cards

    def flush_cards(self):
        self.cards = []

    def set_wight(self, name: str, weight: int) -> bool:
        card = self.get_card(name)
        if card:
            card.weight = max(weight, 0)
            return True
        return False

    def change_wight(self, name: str, wight: int) -> bool:
        card = self.get_card(name)
        if card:
            card.weight += wight
            return True
        return False

    def roll(self) -> Card:
        weights = [card.weight for card in self.cards]
        return random.choices(self.cards, weights=weights)[0]


@dataclass
class RollRecord:
    chat_id: str
    card_set_name: str
    card_name: str
    msg_id: str
    created_by: str
